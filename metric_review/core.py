"""Authenticated synthetic metric receipt review; arithmetic remains in domain."""
import hashlib,json,secrets,sqlite3,threading,time,uuid
from pathlib import Path
from .domain import load_snapshot,analyze
from . import routing
PROFILES={
 'analyst':{'id':'analyst','role':'analyst','authorized_sites':['PLANT-A']},
 'reviewer':{'id':'reviewer','role':'reviewer','authorized_sites':['PLANT-A']},
 'other-site':{'id':'other-site','role':'analyst','authorized_sites':['PLANT-B']}}
LABELS={'baseline':'정상 A+B · 가중 합산','correction_review':'수정 전후 cutoff','conflicting_revision':'동일 revision 충돌','missing_time_b':'B 시간 누락','unknown_unit_b':'B 단위 미지원','missing_good':'양품 수량 누락','performance_over_100':'성능 100% 초과','duplicate_counts':'동일 수량 replay','duplicate_time':'동일 시간 replay','one_to_many_counts':'1:N 수량 조인','cumulative_counts':'누적 수량 미지원','mixed_products':'제품 혼합 미지원','mixed_cycle_versions':'cycle 버전 혼합 미지원'}
DEFAULT_DATE='2026-10-01'
DEFAULT_CUTOFF='2026-10-02T00:30:00+09:00'
def clone(v):return json.loads(json.dumps(v,ensure_ascii=False,allow_nan=False))
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def now():return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
class AuthenticationError(PermissionError):pass
class WorkflowConflictError(ValueError):pass
class Store:
 def __init__(self,data_dir,db_path):
  self.data_dir=Path(data_dir);self._lock=threading.RLock();self._sessions={}
  self._db=sqlite3.connect(str(db_path),check_same_thread=False,timeout=10)
  self._db.execute('PRAGMA journal_mode=WAL')
  self._db.executescript('CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,site_id TEXT NOT NULL,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS reviews(receipt_id TEXT PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT,site_id TEXT NOT NULL,payload TEXT NOT NULL);')
  self._db.commit();self._load()
 def close(self):
  with self._lock:self._db.close()
 def _load(self):
  try:return load_snapshot(self.data_dir)
  except (ValueError,OSError,KeyError,TypeError):raise WorkflowConflictError('snapshot_unavailable') from None
 def _check(self,principal):
  if not isinstance(principal,dict) or principal.get('id') not in PROFILES or principal!=PROFILES[principal['id']]:raise AuthenticationError('invalid_principal')
 def _site(self,principal,site_id):
  self._check(principal)
  if not isinstance(site_id,str) or site_id not in principal['authorized_sites']:raise PermissionError('site_denied')
 def profiles(self):return clone(list(PROFILES.values()))
 def session(self,profile):
  if not isinstance(profile,str) or profile not in PROFILES:raise ValueError('unknown_profile')
  token=secrets.token_urlsafe(32)
  with self._lock:self._sessions[token]=(clone(PROFILES[profile]),time.monotonic()+3600)
  return {'token':token,'principal':clone(PROFILES[profile]),'demo_identity':True}
 def principal(self,token):
  with self._lock:
   row=self._sessions.get(token)
   if not row or row[1]<=time.monotonic():raise AuthenticationError('expired_session')
   return clone(row[0])
 def _dataset(self,snapshot,dataset_id,site_id):
  if not isinstance(dataset_id,str):raise ValueError('invalid_dataset')
  for item in snapshot['manifest']['datasets']:
   if item['dataset_id']==dataset_id:
    keys=[k for k in item['expected_keys'] if k['site_id']==site_id]
    if not keys:raise PermissionError('dataset_site_denied')
    return dict(item,expected_keys=keys)
  raise KeyError('dataset_not_found')
 def datasets(self,principal):
  self._check(principal);s=self._load();out=[]
  for item in s['manifest']['datasets']:
   for site in principal['authorized_sites']:
    keys=[k for k in item['expected_keys'] if k['site_id']==site]
    if keys:out.append({'id':item['dataset_id'],'label':LABELS.get(item['dataset_id'],item['dataset_id']),'site_id':site,'business_date':item['expected_business_date'],'timezone':item['timezone'],'expected_shifts':[k['shift_id'] for k in keys]})
  return out
 def catalog(self,principal):
  self._check(principal);s=self._load()
  # Only approved metric definitions and cycles for visible product/cycle keys.
  allowed={(k['product_id'],k['cycle_version']) for item in s['manifest']['datasets'] for k in item['expected_keys'] if k['site_id'] in principal['authorized_sites']}
  cat=clone(s['catalog']);cat['cycles']=[r for r in cat['cycles'] if (r['product_id'],r['cycle_version']) in allowed]
  return cat
 def sources(self,principal,dataset_id,site_id):
  self._site(principal,site_id);s=self._load();manifest=self._dataset(s,dataset_id,site_id)
  out={};hashes={};row_texts={}
  for kind,label in [('mes_counts','counts'),('shift_time','times')]:
   source=s['sources'][kind]
   out[label]=[clone(r) for r in source['records'] if r.get('dataset_id')==dataset_id and r.get('site_id')==site_id]
   # Preserve authorized source integers across JavaScript's JSON-number boundary.
   # The text is a server serialization of the row, not the export's byte layout.
   row_texts[label]=[{'record_id':r.get('record_id'),'revision_exact':str(r.get('revision')),'record_sha256':digest(r),'record_text':json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),'key_text':json.dumps({k:r.get(k) for k in ('site_id','line_id','business_date','shift_id','product_id','cycle_version')},ensure_ascii=False,allow_nan=False),'issued_at':r.get('issued_at')} for r in out[label]]
   hashes[kind]=source['source_sha256']
  return {'sources':out,'source_rows_text':row_texts,'provenance':hashes,'manifest':manifest,'historical_record_time':True,'export_received_at':{k:v['receipt']['received_at'] for k,v in s['sources'].items()}}
 def _request(self,principal,body,snapshot):
  if not isinstance(body,dict) or set(body)!={'dataset_id','site_id','business_date','as_of_cutoff','metric_id','scope'}:raise ValueError('explicit_selectors_required')
  site=body.get('site_id','PLANT-A');self._site(principal,site)
  dataset=body.get('dataset_id','baseline');self._dataset(snapshot,dataset,site)
  scope=body.get('scope','combined');metric=body.get('metric_id','oee')
  if scope not in routing.SCOPES or metric not in routing.METRICS:raise ValueError('approved_selector_required')
  date=body.get('business_date',DEFAULT_DATE);cutoff=body.get('as_of_cutoff',DEFAULT_CUTOFF)
  if not isinstance(date,str) or not isinstance(cutoff,str):raise ValueError('explicit_calendar_date_and_cutoff_required')
  return {'dataset_id':dataset,'site_id':site,'business_date':date,'as_of_cutoff':cutoff,'metric_id':metric,'scope':scope}
 def _event(self,principal,site,action,**fields):
  event={'at':now(),'actor':principal['id'],'action':action,**fields}
  self._db.execute('INSERT INTO audit(site_id,payload) VALUES(?,?)',(site,json.dumps(event,ensure_ascii=False)))
 def calculate(self,principal,body):
  with self._lock:
   if not isinstance(body,dict) or set(body)!={'dataset_id','site_id','business_date','as_of_cutoff','metric_id','scope'}:raise ValueError('explicit_selectors_required')
   self._site(principal,body['site_id'])
   snapshot=self._load();request=self._request(principal,body,snapshot)
   result=analyze(snapshot['sources'],snapshot['manifest'],snapshot['catalog'],dataset_id=request['dataset_id'],business_date=request['business_date'],as_of_cutoff=request['as_of_cutoff'],authorized_sites=[request['site_id']],metric_id=request['metric_id'],shift_ids=None if request['scope']=='combined' else [request['scope']])
   if result.get('status')=='clarification_required':raise ValueError('explicit_selector_required')
   if self._load()['snapshot_hash']!=snapshot['snapshot_hash']:raise WorkflowConflictError('source_changed_during_calculation')
   fingerprint=digest({'snapshot_hash':snapshot['snapshot_hash'],'rule_version':snapshot['catalog']['rule_version'],'request':request})
   receipt={'id':uuid.uuid4().hex,'fingerprint':fingerprint,'snapshot_hash':snapshot['snapshot_hash'],'created_at':now(),'site_id':request['site_id'],'request':request,'result':result,'review':None,'stale':False}
   with self._db:
    self._db.execute('INSERT INTO receipts VALUES(?,?,?)',(receipt['id'],receipt['site_id'],json.dumps(receipt,ensure_ascii=False,allow_nan=False)))
    self._event(principal,receipt['site_id'],'receipt_created',receipt_id=receipt['id'],fingerprint=fingerprint)
   return clone(receipt)
 def _stored(self,principal,receipt_id):
  self._check(principal)
  if not isinstance(receipt_id,str) or len(receipt_id)>100:raise KeyError('not_found')
  row=self._db.execute('SELECT site_id,payload FROM receipts WHERE id=?',(receipt_id,)).fetchone()
  if not row:raise KeyError('not_found')
  self._site(principal,row[0]);return json.loads(row[1])
 def _fresh(self,receipt):
  try:s=self._load()
  except WorkflowConflictError:return False
  return s['snapshot_hash']==receipt['snapshot_hash'] and digest({'snapshot_hash':s['snapshot_hash'],'rule_version':s['catalog']['rule_version'],'request':receipt['request']})==receipt['fingerprint']
 def receipt(self,principal,receipt_id):
  with self._lock:
   receipt=self._stored(principal,receipt_id)
   if not self._fresh(receipt):return {'id':receipt['id'],'site_id':receipt['site_id'],'request':receipt['request'],'fingerprint':receipt['fingerprint'],'result':None,'review':None,'stale':True,'status':'stale_source'}
   row=self._db.execute('SELECT payload FROM reviews WHERE receipt_id=?',(receipt_id,)).fetchone()
   if row:receipt['review']=json.loads(row[0])
   return receipt
 def review(self,principal,receipt_id,comment,expected_fingerprint):
  self._check(principal)
  if principal['role']!='reviewer':raise PermissionError('reviewer_required')
  if not isinstance(comment,str) or len(comment)>1000:raise ValueError('invalid_comment')
  with self._lock:
   with self._db:
    self._db.execute('BEGIN IMMEDIATE')
    receipt=self._stored(principal,receipt_id)
    if not isinstance(expected_fingerprint,str) or expected_fingerprint!=receipt['fingerprint']:raise WorkflowConflictError('fingerprint_mismatch')
    if not self._fresh(receipt):raise WorkflowConflictError('receipt_stale')
    row=self._db.execute('SELECT payload FROM reviews WHERE receipt_id=?',(receipt_id,)).fetchone()
    if row:
     existing=json.loads(row[0])
     if existing['comment']!=comment:raise WorkflowConflictError('review_already_recorded')
     return {'review':existing,'duplicate':True}
    review={'receipt_id':receipt_id,'actor':principal['id'],'recorded_at':now(),'comment':comment,'fingerprint':expected_fingerprint,'scope':'arithmetic_receipt_acknowledgement_not_factory_certification'}
    self._db.execute('INSERT INTO reviews VALUES(?,?)',(receipt_id,json.dumps(review,ensure_ascii=False)))
    self._event(principal,receipt['site_id'],'receipt_reviewed',receipt_id=receipt_id,fingerprint=expected_fingerprint)
   return {'review':review,'duplicate':False}

 def audit(self,principal):
  self._check(principal)
  with self._lock:
   out=[]
   for site,payload in self._db.execute('SELECT site_id,payload FROM audit ORDER BY sequence'):
    if site in principal['authorized_sites']:out.append(json.loads(payload))
   return out
 def route(self,principal,body):
  self._check(principal)
  if not isinstance(body,dict) or set(body)-{'query','mode','site_id'}:raise ValueError('invalid_route_body')
  site=body.get('site_id','PLANT-A');self._site(principal,site)
  if not any(d['site_id']==site for d in self.datasets(principal)):raise PermissionError('no_authorized_scope')
  mode=body.get('mode','keyword')
  if mode not in ('keyword','model'):raise ValueError('invalid_route_mode')
  function=routing.route_keyword if mode=='keyword' else routing.route_model
  route=function(body.get('query'),principal['authorized_sites'],site)
  return route
