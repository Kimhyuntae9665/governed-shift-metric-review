import json,tempfile,threading,unittest,shutil,time
from pathlib import Path
from unittest.mock import patch
from metric_review.core import Store,PROFILES,AuthenticationError,WorkflowConflictError
from metric_review import routing,llm
DATA=Path(__file__).resolve().parents[1]/'data'
BASE={'dataset_id':'baseline','site_id':'PLANT-A','business_date':'2026-10-01','as_of_cutoff':'2026-10-02T00:30:00+09:00','metric_id':'oee','scope':'combined'}
class CoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.data=Path(self.tmp.name)/'data';shutil.copytree(DATA,self.data)
  self.store=Store(self.data,Path(self.tmp.name)/'test.sqlite');self.addCleanup(self.store.close)
 def calculate(self,principal,updates):return self.store.calculate(principal,dict(BASE,**updates))
 def test_sessions_are_server_owned_copies_and_expire(self):
  session=self.store.session('analyst');token=session['token']
  session['principal']['authorized_sites'].append('PLANT-SECRET')
  self.assertEqual(self.store.principal(token),PROFILES['analyst'])
  self.store._sessions[token]=(PROFILES['analyst'],0)
  with self.assertRaises(AuthenticationError):self.store.principal(token)
 def test_no_unauthorized_rows_in_sources_catalog_or_datasets(self):
  source=self.store.sources(PROFILES['analyst'],'unauthorized_site','PLANT-A')
  self.assertNotIn('PLANT-SECRET',json.dumps(source))
  self.assertEqual(self.store.datasets(PROFILES['other-site']),[])
  with self.assertRaises(PermissionError):self.store.sources(PROFILES['other-site'],'baseline','PLANT-A')
 def test_baseline_and_scope_exact_receipts(self):
  all_=self.calculate(PROFILES['analyst'],{})
  self.assertEqual(all_['result']['combined']['metrics']['oee']['exact'],'147/160')
  a=self.calculate(PROFILES['analyst'],{'scope':'A'})
  self.assertEqual(a['result']['combined']['metrics']['oee']['exact'],'27/40')
  b=self.calculate(PROFILES['analyst'],{'scope':'B'})
  self.assertEqual(b['result']['combined']['metrics']['oee']['exact'],'1')
 def test_cutoff_and_metric_changes_fingerprint_without_rewriting_historical(self):
  before=self.calculate(PROFILES['reviewer'],{'dataset_id':'correction_review','as_of_cutoff':'2026-10-01T23:30:00+09:00'})
  after=self.calculate(PROFILES['reviewer'],{'dataset_id':'correction_review'})
  self.assertEqual(before['result']['combined']['metrics']['oee']['exact'],'11/12')
  self.assertNotEqual(before['fingerprint'],after['fingerprint'])
  self.assertFalse(self.store.receipt(PROFILES['reviewer'],before['id'])['stale'])
 def test_missing_pair_blocks_complete_oee_but_per_shift_survives(self):
  receipt=self.calculate(PROFILES['analyst'],{'dataset_id':'missing_time_b'})
  self.assertIsNone(receipt['result']['combined']['metrics']['oee']['exact'])
  self.assertEqual(receipt['result']['coverage']['accepted_pairs'],1)
  self.assertEqual(receipt['result']['coverage']['expected_pairs'],2)
 def test_review_permission_fingerprint_and_duplicate(self):
  r=self.calculate(PROFILES['analyst'],{})
  with self.assertRaises(PermissionError):self.store.review(PROFILES['analyst'],r['id'],'',r['fingerprint'])
  with self.assertRaises(WorkflowConflictError):self.store.review(PROFILES['reviewer'],r['id'],'','wrong')
  first=self.store.review(PROFILES['reviewer'],r['id'],'checked',r['fingerprint'])
  second=self.store.review(PROFILES['reviewer'],r['id'],'checked',r['fingerprint'])
  self.assertFalse(first['duplicate']);self.assertTrue(second['duplicate'])
  with self.assertRaises(WorkflowConflictError):self.store.review(PROFILES['reviewer'],r['id'],'different',r['fingerprint'])
  self.assertEqual(len([e for e in self.store.audit(PROFILES['reviewer']) if e['action']=='receipt_reviewed']),1)
 def test_concurrent_duplicate_review_one_audit(self):
  r=self.calculate(PROFILES['reviewer'],{})
  outcomes=[]
  def call():outcomes.append(self.store.review(PROFILES['reviewer'],r['id'],'',r['fingerprint'])['duplicate'])
  threads=[threading.Thread(target=call) for _ in range(8)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(outcomes.count(False),1);self.assertEqual(outcomes.count(True),7)
 def test_other_site_receipt_and_audit_denied(self):
  r=self.calculate(PROFILES['reviewer'],{})
  with self.assertRaises(PermissionError):self.store.receipt(PROFILES['other-site'],r['id'])
  self.assertEqual(self.store.audit(PROFILES['other-site']),[])
 def test_frozen_source_tamper_hides_old_result_and_blocks_review(self):
  r=self.calculate(PROFILES['reviewer'],{})
  f=self.data/'mes_counts.json';f.write_text(f.read_text()+' ')
  old=self.store.receipt(PROFILES['reviewer'],r['id'])
  self.assertTrue(old['stale']);self.assertIsNone(old['result']);self.assertIsNone(old['review'])
  with self.assertRaises(WorkflowConflictError):self.store.review(PROFILES['reviewer'],r['id'],'',r['fingerprint'])
 def test_unknown_fields_schema_and_selectors(self):
  for body in ({'sql':'select 1'},{'scope':False},{'metric_id':'uptime'},{'as_of_cutoff':'2026-10-01'},{'business_date':'2026-10-02'}):
   with self.subTest(body=body):
    with self.assertRaises((ValueError,WorkflowConflictError)):self.calculate(PROFILES['analyst'],body)
 def test_route_has_no_receipt_or_math_side_effect(self):
  route=self.store.route(PROFILES['analyst'],{'query':'A교대 OEE','mode':'keyword'})
  self.assertEqual(route['scope'],'A')
  self.assertEqual(self.store.audit(PROFILES['analyst']),[])
  self.assertEqual(self.store._db.execute('SELECT count(*) FROM receipts').fetchone()[0],0)
 def test_cutoff_and_full_selector_must_be_explicit(self):
  with self.assertRaises(ValueError):self.store.calculate(PROFILES['analyst'],{})
  partial=dict(BASE);partial.pop('as_of_cutoff')
  with self.assertRaises(ValueError):self.store.calculate(PROFILES['analyst'],partial)
 def test_unauthorized_site_denied_before_snapshot_query(self):
  with patch.object(self.store,'_load') as load:
   with self.assertRaises(PermissionError):self.calculate(PROFILES['other-site'],{})
   load.assert_not_called()
 def test_cross_store_concurrent_review_one_audit(self):
  other=Store(self.data,Path(self.tmp.name)/'test.sqlite');self.addCleanup(other.close)
  r=self.calculate(PROFILES['reviewer'],{});barrier=threading.Barrier(2);out=[];errors=[]
  def call(store):
   try:
    barrier.wait();out.append(store.review(PROFILES['reviewer'],r['id'],'same',r['fingerprint'])['duplicate'])
   except Exception as error:errors.append(type(error).__name__)
  threads=[threading.Thread(target=call,args=(store,)) for store in (self.store,other)]
  for thread in threads:thread.start()
  for thread in threads:thread.join()
  self.assertEqual(errors,[]);self.assertEqual(sorted(out),[False,True])
  self.assertEqual(len([e for e in self.store.audit(PROFILES['reviewer']) if e['action']=='receipt_reviewed']),1)
class RoutingTests(unittest.TestCase):
 def test_approved_bilingual_metric_scopes(self):
  for query,metric,scope in [('A교대 OEE','oee','A'),('shift B quality','quality','B'),('두 교대 가용성','availability','combined'),('전체 성능률','performance','combined')]:
   route=routing.route_keyword(query,['PLANT-A'],'PLANT-A')
   self.assertEqual((route['metric_id'],route['scope']),(metric,scope))
 def test_ambiguous_and_sql_requests_do_not_invoke_model(self):
  with patch.object(llm,'request_json') as request:
   for query in ['가동률','uptime','지난 교대 OEE','SELECT * FROM mes']:
    route=routing.route_model(query,['PLANT-A'],'PLANT-A')
    self.assertNotEqual(route['action'],'calculate');self.assertFalse(route['model_requested'])
   request.assert_not_called()
 def test_unauthorized_request_denied_before_model(self):
  with patch.object(llm,'request_json') as request:
   with self.assertRaises(PermissionError):routing.route_model('PLANT-SECRET OEE',['PLANT-A'],'PLANT-A')
   with self.assertRaises(PermissionError):routing.route_model('OEE',['PLANT-B'],'PLANT-A')
   request.assert_not_called()
 def test_model_receives_query_only_and_finite_catalog(self):
  proposal={'metric':'oee'}
  with patch.object(llm,'request_json',return_value=(proposal,{'thinking_chars':0},{},{})) as request:
   out=routing.route_model('두 교대 종합설비효율',['PLANT-A'],'PLANT-A')
  self.assertEqual(out['method'],'model')
  messages,schema=request.call_args.args[:2]
  self.assertEqual(messages[1]['content'],'두 교대 종합설비효율')
  self.assertNotIn('source_rows',json.dumps(messages));self.assertNotIn('evaluations',json.dumps(messages))
  self.assertEqual(set(schema['properties']),{'metric'});self.assertEqual(set(schema['properties']['metric']['enum']),{*routing.METRICS,'clarify','unsupported'})
  self.assertEqual(request.call_args.kwargs['num_predict'],256)
  for query,expected in [('A교대 양품 비중','A'),('B교대 양품 비중','B'),('교대 A 품질','A'),('shift B quality','B'),('전체 양품 비중','combined')]:
   with patch.object(llm,'request_json',return_value=({'metric':'quality'}, {}, {}, {})):
    self.assertEqual(routing.route_model(query,['PLANT-A'],'PLANT-A')['scope'],expected)

 def test_invalid_or_inconsistent_model_route_rejected(self):
  for proposal in [{'metric':'profit'},{'metric':None},{'metric':'oee','extra':'ignored'},{'action':'calculate','metric_id':'oee','scope':None,'reason_code':'selected_catalog'}]:
   with patch.object(llm,'request_json',return_value=(proposal,{},None,None)):
    with self.assertRaises(RuntimeError):routing.route_model('OEE',['PLANT-A'],'PLANT-A')
 def test_model_failure_never_becomes_keyword_success(self):
  with patch.object(llm,'request_json',side_effect=TimeoutError('test')):
   with self.assertRaises(TimeoutError):routing.route_model('OEE',['PLANT-A'],'PLANT-A')
 def test_query_budget_rejects_before_network(self):
  with patch.object(llm,'request_json') as request:
   with self.assertRaises(ValueError):routing.route_model('가'*1000,['PLANT-A'],'PLANT-A')
   request.assert_not_called()
if __name__=='__main__':unittest.main()
