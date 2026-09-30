"""Actual P04 browser tests: stdlib CDP, synthetic CPU calculations, no model calls.

Cases and assertions are separate. No evaluator gold import; expected values are
from the approved task contract. Temporary display-boundary checks are labeled.
Only this driver's tab is created/closed in the existing sandboxed Chrome.
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, quote

ROOT=Path(__file__).resolve().parents[1]
APP="http://127.0.0.1:19084"
LATE="2026-10-02T00:30:00+09:00"
EARLY="2026-10-01T23:30:00+09:00"
CASES=[
 {"id":"baseline","dataset":"baseline","cutoff":LATE,"scope":"combined","expected":{"availability":"15/16","performance":"1","quality":"49/50","oee":"147/160"},"image":"01-baseline.png"},
 {"id":"correction-before","dataset":"correction_review","cutoff":EARLY,"scope":"combined","expected":{"oee":"11/12"},"image":"02-correction-before.png"},
 {"id":"correction-after","dataset":"correction_review","cutoff":LATE,"scope":"combined","expected":{"oee":"147/160"},"image":"03-correction-after.png"},
 {"id":"conflicting-revision","dataset":"conflicting_revision","cutoff":LATE,"scope":"combined","expected":{"oee":None},"image":"04-conflicting-revision.png"},
 {"id":"missing-time-b","dataset":"missing_time_b","cutoff":LATE,"scope":"combined","expected":{"availability":None,"performance":None,"quality":"49/50","oee":None},"image":"05-missing-time-b.png"},
 {"id":"unknown-unit-b","dataset":"unknown_unit_b","cutoff":LATE,"scope":"combined","expected":{"availability":None,"quality":"49/50","oee":None},"image":"06-unknown-unit-b.png"},
 {"id":"missing-good","dataset":"missing_good","cutoff":LATE,"scope":"combined","expected":{"availability":"3/4","performance":"1","quality":None,"oee":None},"image":"07-missing-good.png"},
 {"id":"performance-over-100","dataset":"performance_over_100","cutoff":LATE,"scope":"combined","expected":{"performance":"10/9","oee":"3/4"},"image":"08-performance-over-100.png"},
 {"id":"duplicate-counts","dataset":"duplicate_counts","cutoff":LATE,"scope":"combined","expected":{"oee":"27/40"}},
 {"id":"shift-a","dataset":"baseline","cutoff":LATE,"scope":"A","expected":{"oee":"27/40"}},
 {"id":"shift-b","dataset":"baseline","cutoff":LATE,"scope":"B","expected":{"oee":"1"}},
]

class Browser:
 def __init__(self,address):
  loc=urlsplit(address);self.connection=socket.create_connection((loc.hostname,loc.port),timeout=30);self.serial=0
  nonce=base64.b64encode(os.urandom(16)).decode()
  self.connection.sendall((f"GET {loc.path} HTTP/1.1\r\nHost: {loc.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
  response=bytearray()
  while not response.endswith(b"\r\n\r\n"):response.extend(self.read(1))
  assert bytes(response).startswith(b"HTTP/1.1 101"),"CDP handshake failed"
 def read(self,length):
  result=bytearray()
  while len(result)<length:
   part=self.connection.recv(length-len(result))
   if not part:raise RuntimeError("CDP ended")
   result.extend(part)
  return bytes(result)
 def frame(self,payload,opcode=1):
  n=len(payload);prefix=bytes((128|opcode,128|n)) if n<126 else bytes((128|opcode,254))+struct.pack("!H",n) if n<65536 else bytes((128|opcode,255))+struct.pack("!Q",n)
  mask=os.urandom(4);self.connection.sendall(prefix+mask+bytes(c^mask[i%4] for i,c in enumerate(payload)))
 def message(self):
  chunks=[]
  while True:
   flags,length=self.read(2);n=length&127
   if n==126:n=struct.unpack("!H",self.read(2))[0]
   elif n==127:n=struct.unpack("!Q",self.read(8))[0]
   mask=self.read(4) if length&128 else None;payload=self.read(n)
   if mask:payload=bytes(c^mask[i%4] for i,c in enumerate(payload))
   op=flags&15
   if op==8:raise RuntimeError("CDP closed")
   if op==9:self.frame(payload,10);continue
   chunks.append(payload)
   if flags&128:return json.loads(b"".join(chunks).decode())
 def call(self,method,**params):
  self.serial+=1;identity=self.serial;self.frame(json.dumps({"id":identity,"method":method,"params":params}).encode())
  while True:
   result=self.message()
   if result.get("id")==identity:
    if result.get("error"):raise RuntimeError(str(result["error"]))
    return result.get("result",{})
 def js(self,expression):
  reply=self.call("Runtime.evaluate",expression=expression,awaitPromise=True,returnByValue=True)
  if reply.get("exceptionDetails"):raise RuntimeError(str(reply["exceptionDetails"]))
  return reply.get("result",{}).get("value")
 def until(self,expression):return self.js(f"(async()=>{{const end=Date.now()+20000;while(Date.now()<end){{if({expression})return true;await new Promise(r=>setTimeout(r,80));}}throw new Error('UI wait expired');}})()")

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--cdp",default="http://127.0.0.1:19085");args=parser.parse_args()
 with urllib.request.urlopen(urllib.request.Request(args.cdp+"/json/new?"+quote("about:blank",safe=""),method="PUT"),timeout=10) as response:page=json.load(response)
 browser=Browser(page["webSocketDebuggerUrl"]);directory=ROOT/"artifacts"/"browser";directory.mkdir(parents=True,exist_ok=True)
 evidence={"actual_browser":True,"synthetic":True,"model_requests":0,"checks":[],"cases":[],"screenshots":[]}
 def check(condition,label):
  assert browser.js(condition),label
  evidence["checks"].append(label)
 def capture(name):
  browser.call("Page.bringToFront")
  browser.call("Emulation.setPageScaleFactor",pageScaleFactor=1)
  browser.js("(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await new Promise(r=>setTimeout(r,500));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return true;})()")
  check("!/Bearer\\s+[A-Za-z0-9]|BEGIN [A-Z ]*PRIVATE KEY|[A-Z]:\\\\Users|\\b10\\.0\\.0\\.6\\b/.test(document.body.textContent)","capture excludes credentials and private host/path")
  layout=browser.js("(()=>{const t=document.querySelector('#metrics-table').getBoundingClientRect();return {viewport:{width:innerWidth,height:innerHeight},visual_viewport:{width:visualViewport.width,height:visualViewport.height,scale:visualViewport.scale},scroll:{x:scrollX,y:scrollY},table:{top:t.top,bottom:t.bottom,rows:document.querySelectorAll('#metrics-body tr').length}};})()")
  data=base64.b64decode(browser.call("Page.captureScreenshot",format="png",captureBeyondViewport=False)["data"]);(directory/name).write_bytes(data)
  evidence["screenshots"].append({"file":name,"sha256":hashlib.sha256(data).hexdigest(),"actual_ui":True,"paint_settled":True,**layout})
 def calculate(case):
  previous=browser.js("state.receipt?.id || null")
  selectors={"dataset_id":case["dataset"],"site_id":"PLANT-A","business_date":"2026-10-01","as_of_cutoff":case["cutoff"],"metric_id":"oee","scope":case["scope"]}
  browser.js("setRequest("+json.dumps(selectors)+");changed();document.querySelector('#calculate').click()")
  browser.until("!state.busy && !!currentReceipt() && state.receipt.id!=="+json.dumps(previous))
 def assert_case(case):
  for metric,expected in case["expected"].items():check("state.receipt.result.combined.metrics["+json.dumps(metric)+"].exact==="+json.dumps(expected),case["id"]+" exact "+metric)
  check("document.querySelectorAll('#metrics-table thead th')[1].textContent==='교대 A' && document.querySelectorAll('#metrics-table thead th')[2].textContent==='교대 B'",case["id"]+" fixed A/B column headers")
  if case["id"]=="baseline":
   check("state.receipt.result.combined.naive_average_oee.exact==='67/80' && state.receipt.result.combined.naive_average_gap_percentage_points.exact==='65/8'","baseline average and gap are server exact values")
   check("document.querySelector('#metrics-table').textContent.includes('91.8750%') && document.querySelector('#naive-average').textContent.includes('83.7500%') && document.querySelector('#average-gap').textContent.includes('8.1250 pp')","percent decimal strings retain four decimals without regrouping or rounding")
   check("state.receipt.result.coverage.expected_pairs===2 && state.receipt.result.coverage.accepted_pairs===2","baseline expected manifest coverage A+B")
   check("state.receipt.result.conversions.some(r=>r.record_id==='TIME-B'&&r.source_unit==='min'&&r.multiplier_exact==='60'&&r.output_exact==='10800')","explicit minute-to-second conversion preserved")
  if case["id"]=="correction-before":check("state.receipt.result.accepted.counts.find(r=>r.record_id==='COUNT-A').revision===1","early cutoff selects original record revision1")
  if case["id"]=="correction-after":check("state.receipt.result.accepted.counts.find(r=>r.record_id==='COUNT-A').revision===2","later cutoff selects corrected record revision2")
  if case["id"]=="conflicting-revision":check("state.receipt.result.quarantine.some(r=>r.reason==='conflicting_revision') && !state.receipt.result.accepted.counts.some(r=>r.record_id==='COUNT-A')","conflicting revision quarantined without fallback")
  if case["id"] in ["missing-time-b","unknown-unit-b"]:
   check("state.receipt.result.coverage.expected_pairs===2 && state.receipt.result.coverage.accepted_pairs===1","incomplete scope retains A+B expectation")
   check("document.querySelector('#metrics-table').textContent.includes('정의되지 않음') && document.querySelector('#coverage-banner').classList.contains('warning')","undefined incomplete combined results stay visible")
  if case["id"]=="performance-over-100":check("document.querySelector('#metrics-table').textContent.includes('111.1111%') && document.querySelector('#metric-flags').textContent.includes('100% 초과')","performance above100 is retained and flagged")
  if case["id"]=="duplicate-counts":check("state.receipt.result.replays.length>0 && state.receipt.result.accepted.counts.length===1","exact duplicate replay skipped once")
  if case["scope"] in ['A','B']:check("document.querySelectorAll('#metrics-body tr')[3].cells["+str(2 if case["scope"]=='A' else 1)+"].textContent.includes('범위 외')","nonselected shift shown outside scope")
  evidence["cases"].append({"id":case["id"],"dataset":case["dataset"],"cutoff":case["cutoff"],"scope":case["scope"],"passed":True})
 try:
  browser.call("Page.enable");browser.call("Runtime.enable");browser.call("Emulation.setDeviceMetricsOverride",width=1440,height=1200,deviceScaleFactor=1,mobile=False)
  browser.call("Page.navigate",url=APP);browser.until("typeof state!=='undefined' && state.token && !state.busy && state.datasets.length>0")
  check("document.querySelector('#route-mode').value==='keyword'","default intent proposal is CPU keyword mode")
  for case in CASES:
   calculate(case);assert_case(case)
   if case.get("image"):capture(case["image"])
  calculate(CASES[0]);browser.js("document.querySelector('[data-evidence-index=\"0\"]').click()")
  browser.until("document.querySelector('#evidence-dialog').open && !state.busy")
  check("document.querySelector('#original-row').textContent.includes('COUNT-A') && document.querySelector('#evidence-meta').textContent.includes('SHA-256')","source drawer original record and hash provenance")
  tree=browser.call("Accessibility.getFullAXTree")
  dialog_nodes=[n for n in tree["nodes"] if n.get("role",{}).get("value")=="dialog" and not n.get("ignored")]
  assert any(n.get("name",{}).get("value")=="COUNT-A · 개정 2" for n in dialog_nodes),"native AX dialog accessible name"
  evidence["checks"].append("native accessibility tree dialog name matches evidence title")
  check("document.activeElement.id==='close-evidence'","native evidence dialog initially focuses close control")
  check("document.querySelector('#evidence-provenance').textContent.includes('2026-10-02T01:00:00+09:00')","receipt time remains later than historical cutoffs")
  capture("09-original-evidence.png");browser.js("document.querySelector('#close-evidence').click()");browser.until("document.activeElement.dataset.evidenceIndex==='0'")
  check("document.activeElement.dataset.evidenceIndex==='0'","drawer close restores originating source focus")
  browser.js("document.querySelector('[data-evidence-index=\"0\"]').click()")
  browser.until("document.querySelector('#evidence-dialog').open && !state.busy")
  browser.call("Input.dispatchKeyEvent",type="keyDown",key="Escape",code="Escape",windowsVirtualKeyCode=27,nativeVirtualKeyCode=27)
  browser.call("Input.dispatchKeyEvent",type="keyUp",key="Escape",code="Escape",windowsVirtualKeyCode=27,nativeVirtualKeyCode=27)
  browser.until("!document.querySelector('#evidence-dialog').open && document.activeElement.dataset.evidenceIndex==='0'")
  check("document.activeElement.dataset.evidenceIndex==='0'","Escape keyboard dismissal restores originating source focus")
  browser.js("document.querySelector('#intent-query').value='A와 B 합산 성능률';document.querySelector('#route-submit').click()")
  browser.until("!state.busy && !!state.route")
  check("state.route.action==='calculate' && document.querySelector('#metric').value==='oee' && document.querySelector('#calculate').disabled","intent proposal does not silently apply or calculate")
  check("document.querySelector('#apply-route').disabled","human proposal acknowledgement required")
  capture("10-intent-proposal.png")
  browser.js("document.querySelector('#route-ack').checked=true;document.querySelector('#route-ack').dispatchEvent(new Event('change'));document.querySelector('#apply-route').click()")
  check("document.querySelector('#metric').value==='performance' && !state.route && !currentReceipt()","human applies explicit metric/scope and hides previous receipt")
  calculate(CASES[0]);check("document.querySelector('#review-form').hidden","analyst cannot acknowledge receipt review")
  browser.js("document.querySelector('#profile').value='reviewer';document.querySelector('#profile').dispatchEvent(new Event('change'))")
  browser.until("!state.busy && state.principal.role==='reviewer'")
  check("!!currentReceipt() && !document.querySelector('#review-form').hidden && document.querySelector('#review-submit').disabled","reviewer sees same fresh receipt and separate acknowledgement gate")
  browser.js("document.querySelector('#review-ack').checked=true;document.querySelector('#review-ack').dispatchEvent(new Event('change'));document.querySelector('#review-submit').click()")
  browser.until("!state.busy && !!state.receipt.review")
  check("document.querySelector('#review-badge').textContent==='확인 기록됨'","arithmetic receipt acknowledgement recorded")
  duplicate=browser.js("(async()=>{const r=state.receipt;const response=await api('/api/receipts/'+r.id+'/review',{comment:'',expected_fingerprint:r.fingerprint});return response.duplicate;})()")
  assert duplicate is True,"duplicate review idempotence";evidence["checks"].append("duplicate receipt acknowledgement is idempotent")
  capture("11-review-recorded.png")
  browser.js("document.querySelector('#cutoff').value='2026-10-01T23:30:00+09:00';document.querySelector('#cutoff').dispatchEvent(new Event('change'))")
  check("!currentReceipt() && document.querySelector('#review-form').hidden && !document.querySelector('#metrics-table').textContent.includes('91.8750%')","changed cutoff hides historical receipt result and review until recalculation")
  calculate(CASES[0])
  browser.call("Emulation.setTimezoneOverride",timezoneId="America/Los_Angeles")
  check("document.querySelector('#business-date').value==='2026-10-01' && state.receipt.request.as_of_cutoff==='2026-10-02T00:30:00+09:00'","explicit business date and offset cutoff do not shift under Los_Angeles")
  browser.call("Emulation.setTimezoneOverride",timezoneId="UTC")
  check("[...document.querySelectorAll('td,th,.small,.status-pill')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=14)","dense table and metadata fonts at least14px")
  check("[...document.querySelectorAll('input,select,textarea,.primary,.secondary,.long-body,.body-note')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=16)","main controls and long body fonts at least16px")
  browser.js("(()=>{window.testOriginalReceipt=state.receipt;state.receipt={...state.receipt,stale:true,result:null,review:null};render();})()")
  check("!currentReceipt() && document.querySelector('#review-form').hidden && !document.querySelector('#metrics-table').textContent.includes('91.8750%')","stale source receipt shell hides result and review (browser display-boundary regression)")
  browser.js("state.receipt=window.testOriginalReceipt;delete window.testOriginalReceipt;render()")
  browser.js("(()=>{const m=state.receipt.result.combined.metrics.performance;window.testOriginalMetric={...m};Object.assign(m,{exact:'9007199254740993',percentage_4dp:'9007199254740993.0000',numerator_exact:'9007199254740993',denominator_exact:'1'});renderMetrics(currentReceipt());})()")
  check("document.querySelector('#metrics-table').textContent.includes('9,007,199,254,740,993.0000%') && document.querySelector('#metrics-table').textContent.includes('9007199254740993')","large exact percentage and fraction strings render without Number conversion (browser display-boundary regression)")
  browser.js("state.receipt.result.combined.metrics.performance=window.testOriginalMetric;delete window.testOriginalMetric;renderMetrics(currentReceipt())")
  contrast=browser.js("""(()=>{const rgb=s=>s.match(/[\\d.]+/g).map(Number);const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);const out=[];for(const e of document.querySelectorAll('p,td,th,label,.status-pill,.muted,.eyebrow,button,footer')){if(!e.textContent.trim()||!e.getClientRects().length)continue;let n=e,bg;while(n){const c=rgb(getComputedStyle(n).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}n=n.parentElement;}if(!bg)bg=[255,255,255];const a=lum(rgb(getComputedStyle(e).color)),b=lum(bg);out.push({text:e.textContent.trim().slice(0,35),ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)});}return out.sort((a,b)=>a.ratio-b.ratio);})()""")
  assert contrast[0]["ratio"]>=4.5,str(contrast[0]);evidence["minimum_checked_text_contrast"]=round(contrast[0]["ratio"],3);evidence["checks"].append("visible task text contrast at least4.5")
  check("document.documentElement.scrollWidth<=innerWidth","desktop no horizontal page overflow")
  browser.call("Emulation.setDeviceMetricsOverride",width=720,height=600,deviceScaleFactor=2,mobile=False)
  browser.js("window.scrollTo(0,0)")
  check("document.documentElement.scrollWidth<=innerWidth","200 percent zoom-equivalent reflow has no page overflow");capture("12-zoom-reflow.png")
  browser.call("Emulation.setDeviceMetricsOverride",width=390,height=844,deviceScaleFactor=1,mobile=True)
  browser.js("window.scrollTo(0,0)")
  browser.call("Emulation.setPageScaleFactor",pageScaleFactor=1)
  browser.js("(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await new Promise(r=>setTimeout(r,500));return true;})()")
  check("innerWidth===390 && document.documentElement.scrollWidth<=390 && Math.abs(visualViewport.scale-1)<0.001","mobile layout stays at requested390 CSS pixels without automatic shrinking")
  check("document.documentElement.scrollWidth<=innerWidth","mobile no horizontal page overflow");capture("13-mobile.png")
  browser.js("document.querySelector('.results-panel').scrollIntoView()")
  browser.js("(async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));await new Promise(r=>setTimeout(r,250));return true;})()")
  check("(()=>{const row=document.querySelector('#metrics-body .selected-metric');const box=row.getBoundingClientRect();const target=document.elementFromPoint((box.left+box.right)/2,(box.top+box.bottom)/2);return box.top>=0&&box.bottom<=innerHeight&&target?.closest('tr')===row&&row.textContent.includes('91.8750%');})()","mobile selected metric is visible in viewport without occlusion")
  capture("14-mobile-results.png")
  browser.call("Emulation.setDeviceMetricsOverride",width=1440,height=1200,deviceScaleFactor=1,mobile=False)
  browser.js("window.scrollTo(0,0);document.querySelector('#profile').value='other-site';document.querySelector('#profile').dispatchEvent(new Event('change'))")
  browser.until("!state.busy && state.principal.id==='other-site'")
  check("state.datasets.length===0 && !state.receipt && !state.sources && document.querySelector('#calculate').disabled && !document.querySelector('#metrics-table').textContent.includes('91.8750%')","other-site identity clears previous authorized receipt and source data")
  denied=browser.js("(async()=>{const r=await fetch('/api/sources?dataset_id=baseline&site_id=PLANT-A',{headers:{Authorization:'Bearer '+state.token}});const body=await r.json();return {status:r.status,body:JSON.stringify(body)};})()")
  assert denied["status"]==403 and "COUNT-A" not in denied["body"] and "TIME-A" not in denied["body"],"neutral denied source response";evidence["checks"].append("denied source response neutral without unauthorized row identifiers")
  capture("15-neutral-acl.png")
  evidence["passed"]=True;(directory/"checks.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
  print(json.dumps({"passed":True,"checks":len(evidence["checks"]),"cases":len(evidence["cases"]),"screenshots":len(evidence["screenshots"]),"model_requests":0},ensure_ascii=False))
 except Exception as error:
  evidence.update(passed=False,error=str(error));(directory/"checks.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8");raise
 finally:
  browser.connection.close()
  with urllib.request.urlopen(args.cdp+"/json/close/"+page["id"],timeout=10):pass

if __name__=='__main__':main()
