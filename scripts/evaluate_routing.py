"""Explicit sequential development evaluation; no gold sent to model."""
import pathlib,json,sys,time,subprocess,threading,hashlib,argparse
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from metric_review.routing import route_keyword,route_model
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
 path=ROOT/args.output
 if path.exists():raise SystemExit('Refuse to overwrite an evaluation record')
 f=ROOT/'evaluations/routing_cases.json'
 assert hashlib.sha256(f.read_bytes()).hexdigest()==json.loads((ROOT/'evaluations/routing_freeze.json').read_text())['sha256']
 cases=json.loads(f.read_text())['cases'];path.parent.mkdir(parents=True,exist_ok=True)
 report={'scope':'8 predeclared development cases, not independent heldout','baseline':[],'model':[],'resource_samples':[],'model_requests':0}
 done=threading.Event()
 def sample():
  while not done.is_set():
   try:
    gpu=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()
    ram=next(x for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
    report['resource_samples'].append({'monotonic_s':time.monotonic(),'gpu_used_mib_util':gpu,'ram_available':ram})
   except Exception as e:report['resource_samples'].append({'sample_error':type(e).__name__})
   done.wait(.5)
 threading.Thread(target=sample,daemon=True).start()
 try:
  for case in cases:
   start=time.monotonic();rec={'id':case['id'],'query':case['query']}
   try:rec['route']=route_keyword(case['query'],('PLANT-A',),'PLANT-A')
   except PermissionError:rec['http_status']=403
   report['baseline'].append(rec)
   rec={'id':case['id'],'query':case['query']}
   directory=ROOT/'artifacts/model-calls';before=set(directory.glob('*.json')) if directory.exists() else set()
   try:rec['route']=route_model(case['query'],('PLANT-A',),'PLANT-A')
   except PermissionError:rec['http_status']=403
   except Exception as e:rec['error']=type(e).__name__+': '+str(e)
   rec['elapsed_s']=round(time.monotonic()-start,4)
   after=set(directory.glob('*.json')) if directory.exists() else set()
   rec['trace_files']=[x.name for x in after-before];report['model_requests']+=len(after-before)
   rec['passed']=rec.get('http_status')==case['expected_http_status'] if 'expected_http_status' in case else all(rec.get('route',{}).get(k)==v for k,v in case['expected'].items())
   report['model'].append(rec);path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
   print(json.dumps(rec,ensure_ascii=False),flush=True)
   if rec.get('error','').startswith('TimeoutError'):break
 finally:done.set();path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print('SUMMARY',report['model_requests'],sum(r['passed'] for r in report['model']),len(report['model']))
if __name__=='__main__':main()
