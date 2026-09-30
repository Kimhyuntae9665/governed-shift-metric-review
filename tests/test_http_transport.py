import json,tempfile,threading,unittest,urllib.request,urllib.error,io,socket
from pathlib import Path
from unittest.mock import patch
from metric_review.core import Store
from metric_review.server import make_server
from metric_review import llm
DATA=Path(__file__).resolve().parents[1]/'data'
BASE={'dataset_id':'baseline','site_id':'PLANT-A','business_date':'2026-10-01','as_of_cutoff':'2026-10-02T00:30:00+09:00','metric_id':'oee','scope':'combined'}
class HTTPTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.store=Store(DATA,Path(self.temp.name)/'test.db')
  self.server=make_server(self.store,0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.base='http://127.0.0.1:'+str(self.server.server_port)
  self.addCleanup(self.finish)
  self.tokens={role:self.call('/api/session',{'profile':role})[1]['token'] for role in ('analyst','reviewer','other-site')}
 def finish(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.store.close()
 def call(self,path,body=None,role=None,headers=None):
  h={'Content-Type':'application/json'}
  if role:h['Authorization']='Bearer '+self.tokens[role]
  if headers:h.update(headers)
  request=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=h)
  try:
   with urllib.request.urlopen(request,timeout=5) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as r:return r.code,json.load(r)
 def test_auth_and_real_permission_status_distinct(self):
  self.assertEqual(self.call('/api/datasets')[0],401)
  self.assertEqual(self.call('/api/calculate',BASE,'other-site')[0],403)
  self.assertEqual(self.call('/api/datasets',role='other-site')[1]['datasets'],[])
 def test_host_origin_and_static_allowlist(self):
  self.assertEqual(self.call('/api/health',headers={'Host':'evil.example'})[0],403)
  self.assertEqual(self.call('/api/health',headers={'Origin':'http://evil.example'})[0],403)
  self.assertEqual(self.call('/data/mes_counts.json')[0],404)
  self.assertEqual(self.call('/.env')[0],404)
  response=urllib.request.urlopen(self.base+'/')
  self.assertIn('frame-ancestors',response.headers['Content-Security-Policy']);response.close()
 def test_explicit_selector_query_and_no_arbitrary_sql(self):
  self.assertEqual(self.call('/api/calculate',{},'analyst')[0],400)
  bad=dict(BASE,sql='select 1')
  self.assertEqual(self.call('/api/calculate',bad,'analyst')[0],400)
  self.assertEqual(self.call('/api/sources?dataset_id=baseline&dataset_id=baseline',role='analyst')[0],400)
 def test_receipt_review_and_idempotent_audit(self):
  status,result=self.call('/api/calculate',BASE,'analyst');self.assertEqual(status,200)
  r=result['receipt'];self.assertEqual(r['result']['combined']['metrics']['oee']['exact'],'147/160')
  review={'comment':'synthetic','expected_fingerprint':r['fingerprint']}
  self.assertEqual(self.call('/api/receipts/'+r['id']+'/review',review,'analyst')[0],403)
  self.assertFalse(self.call('/api/receipts/'+r['id']+'/review',review,'reviewer')[1]['duplicate'])
  self.assertTrue(self.call('/api/receipts/'+r['id']+'/review',review,'reviewer')[1]['duplicate'])
  self.assertEqual(self.call('/api/receipts/'+r['id'],role='other-site')[0],403)
  self.assertEqual(self.call('/api/audit',role='other-site')[1]['events'],[])
 def test_source_acl_before_model_request_and_unknown_state(self):
  with patch.object(llm,'request_json') as request:
   self.assertEqual(self.call('/api/route',{'query':'PLANT-SECRET OEE','mode':'model','site_id':'PLANT-A'},'analyst')[0],403)
   route=self.call('/api/route',{'query':'가동률','mode':'model','site_id':'PLANT-A'},'analyst')[1]['route']
   self.assertEqual(route['action'],'clarify');request.assert_not_called()
  sources=self.call('/api/sources?dataset_id=unauthorized_site&site_id=PLANT-A',role='analyst')[1]
  self.assertNotIn('PLANT-SECRET',json.dumps(sources))
 def test_model_failure_is_degraded503_not_keyword_success(self):
  with patch.object(llm,'request_json',side_effect=RuntimeError('private detail')):
   status,result=self.call('/api/route',{'query':'OEE','mode':'model','site_id':'PLANT-A'},'analyst')
   self.assertEqual(status,503);self.assertEqual(result['code'],'model_routing_failed');self.assertNotIn('private detail',json.dumps(result))
class TransportTests(unittest.TestCase):
 def test_bounded_payload_and_response_fields(self):
  raw={'done':True,'done_reason':'stop','message':{'content':'{}','thinking':''},'eval_count':2}
  with tempfile.TemporaryDirectory() as d:
   lock=Path(d)/'inference.lock'
   with patch.object(llm,'INFERENCE_LOCK',lock),patch.object(llm,'_disabled_reason',None),patch.object(llm.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(raw).encode())) as request:
    parsed,metrics,response,payload=llm.request_json([{'role':'user','content':'synthetic'}],{'type':'object'},num_predict=16)
   self.assertEqual(parsed,{})
   self.assertFalse(payload['think']);self.assertFalse(payload['truncate']);self.assertFalse(payload['shift'])
   self.assertEqual(payload['options']['num_ctx'],4096);self.assertEqual(metrics['thinking_chars'],0)
 def test_timeout_marker_blocks_new_client_request(self):
  with tempfile.TemporaryDirectory() as d:
   lock=Path(d)/'inference.lock'
   with patch.object(llm,'INFERENCE_LOCK',lock),patch.object(llm,'_disabled_reason',None),patch.object(llm.urllib.request,'urlopen',side_effect=socket.timeout('synthetic timeout')) as request:
    with self.assertRaises(TimeoutError):llm.request_json([],{'type':'object'})
    self.assertTrue(Path(str(lock)+'.blocked').exists())
   with patch.object(llm,'INFERENCE_LOCK',lock),patch.object(llm,'_disabled_reason',None),patch.object(llm.urllib.request,'urlopen') as request:
    with self.assertRaises(RuntimeError):llm.request_json([],{'type':'object'})
    request.assert_not_called()
if __name__=='__main__':unittest.main()
