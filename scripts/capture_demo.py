"""Native UI capture. One optional actual model request; no synthetic success injection."""
import pathlib,json,time,sys,base64,hashlib,urllib.request,urllib.parse,subprocess,threading
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from browser_check import Browser
DIR=ROOT/'artifacts/demo-recording';DIR.mkdir(parents=True,exist_ok=True)
with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:19085/json/new?about:blank',method='PUT')) as r:page=json.load(r)
b=Browser(page['webSocketDebuggerUrl']);start=time.monotonic();manifest={'actual_browser':True,'synthetic_sources':True,'automated_demo_actions':True,'frames':[],'screenshots':[],'model_requests':0,'resource_samples':[]}
done=threading.Event()
def sample():
 while not done.is_set():
  try:manifest['resource_samples'].append({'gpu_mib_util':subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip(),'ram_available':next(x for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))})
  except Exception as e:manifest['resource_samples'].append({'sample_error':type(e).__name__})
  done.wait(.5)
def frame():
 data=base64.b64decode(b.call('Page.captureScreenshot',format='jpeg',quality=85,captureBeyondViewport=False)['data']);name=f"frame{len(manifest['frames']):04d}.jpg";(DIR/name).write_bytes(data);manifest['frames'].append({'file':name,'at_s':round(time.monotonic()-start,4),'sha256':hashlib.sha256(data).hexdigest()})
def hold(seconds):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:frame();time.sleep(.15)
def screenshot(name):
 assert b.js("!/Bearer\\\\s+[A-Za-z0-9]|PRIVATE KEY|[A-Z]:\\\\\\\\Users|10\\\\.0\\\\.0\\\\.6/.test(document.body.textContent)")
 data=base64.b64decode(b.call('Page.captureScreenshot',format='png',captureBeyondViewport=False)['data']);(DIR/name).write_bytes(data);manifest['screenshots'].append({'file':name,'sha256':hashlib.sha256(data).hexdigest(),'actual_ui':True})
try:
 b.call('Page.enable');b.call('Runtime.enable');b.call('Emulation.setDeviceMetricsOverride',width=1600,height=1200,deviceScaleFactor=1,mobile=False)
 b.call('Page.navigate',url='http://127.0.0.1:19084')
 b.until("typeof state!=='undefined' && state.token && state.datasets.length && !state.busy");hold(.7)
 b.js("document.getElementById('intent-query').value='A교대에서 계획 시간 대비 실제 운영 시간 비율 알려줘';document.getElementById('route-mode').value='model';document.getElementById('route-form').requestSubmit();true")
 threading.Thread(target=sample,daemon=True).start()
 deadline=time.monotonic()+65
 while not b.js('!state.busy'):
  if time.monotonic()>deadline:raise RuntimeError('Model UI request completion unknown; no retry')
  frame();time.sleep(.15)
 assert b.js("state.route?.method==='model' && state.route.metric_id==='availability' && state.route.scope==='A'"),'actual model proposal failed'
 manifest['model_requests']=1;manifest['actual_route']=b.js('state.route')
 b.js("document.getElementById('route-result').scrollIntoView({block:'center'});true");screenshot('16-actual-model-proposal.png');hold(.8)
 b.js("document.getElementById('route-ack').click();document.getElementById('apply-route').click();document.getElementById('calculate-form').requestSubmit();true")
 b.until("!state.busy && currentReceipt()?.result.combined.metrics.availability.exact==='3/4'");b.js("window.scrollTo(0,0);true");screenshot('17-model-applied-cpu-receipt.png');hold(.8)
 b.js("document.getElementById('profile').value='reviewer';document.getElementById('profile').dispatchEvent(new Event('change'));true")
 b.until("!state.busy && state.principal?.role==='reviewer' && currentReceipt()")
 b.js("document.getElementById('review-comment').value='합성 교대 A의 원본 행과 산술 근거를 확인했습니다.';document.getElementById('review-ack').click();document.getElementById('review-form').requestSubmit();true")
 b.until("!state.busy && !!currentReceipt()?.review");screenshot('18-model-flow-review-record.png');hold(.8)
 b.js("document.querySelector('[data-evidence-index]').click();true");b.until("document.getElementById('evidence-dialog').open");screenshot('19-actual-source-drawer.png');hold(1)
 b.js("document.getElementById('close-evidence').click();document.getElementById('metric').value='oee';document.getElementById('scope').value='combined';document.getElementById('scope').dispatchEvent(new Event('change'));document.getElementById('calculate-form').requestSubmit();true")
 b.until("!state.busy && currentReceipt()?.result.combined.metrics.oee.exact==='147/160'");hold(1.2)
finally:
 done.set();manifest['elapsed_s']=round(time.monotonic()-start,4);(DIR/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
 try:
  with urllib.request.urlopen('http://127.0.0.1:19085/json/close/'+page['id']):pass
 except Exception:pass
# Preserve measured inter-frame timing and final hold. No compositing/overlays.
concat=[]
for i,f in enumerate(manifest['frames']):
 duration=manifest['frames'][i+1]['at_s']-f['at_s'] if i+1<len(manifest['frames']) else .25
 concat += ["file '"+f['file']+"'",'duration '+str(max(duration,.001))]
concat += ["file '"+manifest['frames'][-1]['file']+"'"]
(DIR/'frames.txt').write_text('\n'.join(concat)+'\n')
subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i','frames.txt','-vf','fps=30','-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart','workflow.mp4'],cwd=DIR,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True)
print(json.dumps({'screenshots':len(manifest['screenshots']),'frames':len(manifest['frames']),'elapsed_s':manifest['elapsed_s'],'model_requests':manifest['model_requests'],'video_bytes':(DIR/'workflow.mp4').stat().st_size},ensure_ascii=False))
