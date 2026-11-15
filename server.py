"""Local application server. Binds to loopback; static assets and query API only."""
from __future__ import annotations
import argparse, csv, hashlib, io, json, mimetypes, os, re, threading, time, unicodedata, uuid
from collections import OrderedDict
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from concurrent.futures import ThreadPoolExecutor
import engine

ROOT=Path(__file__).resolve().parent;DATA=ROOT/'data';DB=DATA/'fire.sqlite';STATIC=ROOT/'static'
FEEDS={
 'modis':'https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_7d.csv',
 'snpp':'https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_7d.csv',
 'noaa20':'https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_7d.csv',
 'noaa21':'https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_Global_7d.csv'}
MANIFEST=json.loads((DATA/'archive-manifest.json').read_text()) if (DATA/'archive-manifest.json').exists() else {}
COUNTRIES=sorted({re.sub(r'^(modis|viirs-snpp|viirs-jpss1|viirs-jpss2)_\d{4}_','',x)[:-4] for x in MANIFEST if re.match(r'^(modis|viirs-snpp|viirs-jpss1|viirs-jpss2)_\d{4}_',x)})
JOBS={};JOB_LOCK=threading.Lock();POOL=ThreadPoolExecutor(max_workers=1);QUERY_GATE=threading.BoundedSemaphore(3)
CACHE=OrderedDict();CACHE_LOCK=threading.Lock();REVISION=0

def normal(text):return ''.join(x for x in unicodedata.normalize('NFKD',str(text)).casefold() if not unicodedata.combining(x))
def load_places():
 global PLACES,PLACE_KEYS
 PLACES=json.loads((DATA/'cities.json').read_text(encoding='utf-8'))
 PLACE_KEYS=[normal(' '.join(str(x) for x in (p[1],p[2],p[5],p[9]))) for p in PLACES]

def find_places(q):
 q=normal(q.strip())
 if len(q)<2:return []
 tokens=q.split();found=[]
 for p,k in zip(PLACES,PLACE_KEYS):
  if all(t in k for t in tokens):found.append(p)
 found.sort(key=lambda p:(normal(p[1])!=q,not normal(p[1]).startswith(q),-p[7]))
 return [{'id':p[0],'name':p[1],'lat':p[3],'lon':p[4],'country':p[5],'admin':p[6],'population':p[7],'timezone':p[8]} for p in found[:12]]

def metadata():
 with engine.connect(DB) as c:
  ss=[dict(x) for x in c.execute('SELECT * FROM sources ORDER BY tier,id')]
 return {'engine':engine.VERSION,'places':len(PLACES),'countries':COUNTRIES,'sources':ss,'records':sum(x['rows'] for x in ss),'recent_start':min((x['start'] for x in ss if x['tier']=='nrt' and x['start']),default=None),'recent_end':max((x['end'] for x in ss if x['tier']=='nrt' and x['end']),default=None),'attribution':'NASA LANCE/FIRMS · GeoNames CC BY 4.0 · Natural Earth public domain','revision':REVISION}

def cached(kind,s):
 key=json.dumps([REVISION,kind,s],sort_keys=True)
 with CACHE_LOCK:
  if key in CACHE:CACHE.move_to_end(key);return CACHE[key]
 value=engine.historical(DB,s) if kind=='history' else engine.analyze(DB,s)
 with CACHE_LOCK:
  CACHE[key]=value
  while len(CACHE)>30:CACHE.popitem(last=False)
 return value

def archive_plan(body):
 countries=body.get('countries',[])
 if not isinstance(countries,list) or not countries or len(countries)>5 or any(x not in COUNTRIES for x in countries):raise ValueError('Choose 1–5 valid archive countries')
 lo=int(body.get('from',2018));hi=int(body.get('to',2025))
 if lo<2000 or hi>=datetime.now().year or hi<lo or hi-lo>25:raise ValueError('Use completed calendar years from 2000 through last year')
 products=body.get('products',['modis','snpp','noaa20'])
 prefixes={'modis':'modis','snpp':'viirs-snpp','noaa20':'viirs-jpss1','noaa21':'viirs-jpss2'}
 if not isinstance(products,list) or not products or any(x not in prefixes for x in products):raise ValueError('Invalid source products')
 items=[];missing=[]
 with engine.connect(DB) as c:loaded={r[0] for r in c.execute('SELECT id FROM sources')}
 for country in countries:
  for year in range(lo,hi+1):
   for product in products:
    name=f'{prefixes[product]}_{year}_{country}.csv'
    if name not in MANIFEST:missing.append(name);continue
    if name in loaded:continue
    items.append({'id':name,'url':'https://firms.modaps.eosdis.nasa.gov/data/country/'+name,'tier':'standard','country':country,'product':product,'start':f'{year}-01-01','end':f'{year}-12-31','bytes':MANIFEST[name]})
 size=sum(x['bytes'] for x in items)
 if size>600*1024**2:raise ValueError('This batch exceeds 600 MB. Request fewer years or one country at a time.')
 return {'items':items,'missing':missing,'bytes':size,'already_loaded':len(countries)*(hi-lo+1)*len(products)-len(items)-len(missing)}

def fetch_source(item):
 import requests
 cache=DATA/'cache';cache.mkdir(exist_ok=True);target=cache/item['id'];part=cache/(item['id']+'.part')
 try:
  with requests.get(item['url'],stream=True,timeout=(15,90),headers={'User-Agent':'BurnWindow/1.0 (NASA Space Apps research)'}) as r:
   r.raise_for_status();size=0
   with part.open('wb') as f:
    for chunk in r.iter_content(262144):
     size+=len(chunk)
     if size>350*1024**2:raise ValueError('Download exceeded the per-source size limit')
     f.write(chunk)
  result=engine.ingest(DB,part,item);part.replace(target);return result
 finally:
  if part.exists():part.unlink()

def run_job(jobid,items):
 global REVISION
 job=JOBS[jobid];job['state']='running'
 for item in items:
  if job.get('cancel'):break
  job['current']=item['id']
  try:result=fetch_source(item);job['results'].append(result);REVISION+=1
  except Exception as e:job['errors'].append({'source':item['id'],'message':str(e)[:450]})
  job['done']+=1
 job['state']='cancelled' if job.get('cancel') else 'partial' if job['errors'] else 'complete';job['current']=None

def new_job(items):
 with JOB_LOCK:
  active=next((j for j in JOBS.values() if j['state'] in ('queued','running')),None)
  if active:raise ValueError('An ingestion job is already running. Wait or cancel it in Data & evidence.')
  if len(JOBS)>30:
   for key in list(JOBS)[:-20]:JOBS.pop(key,None)
  jobid=uuid.uuid4().hex[:12];JOBS[jobid]={'id':jobid,'state':'queued','total':len(items),'done':0,'results':[],'errors':[],'current':None}
 POOL.submit(run_job,jobid,items)
 return JOBS[jobid].copy()

def overview(sensor):
 if sensor not in engine.SENSORS:raise ValueError('Unknown platform')
 with engine.connect(DB) as c:
  result=c.execute('''SELECT round(p.lat) lat,round(p.lon) lon,count(*) n FROM points p JOIN sources s ON s.id=p.source
    WHERE s.tier='nrt' AND p.sensor=? AND p.quality=1 GROUP BY round(p.lat),round(p.lon)''',(sensor,)).fetchall()
 return {'cells':[dict(x) for x in result],'unit':'Reports in approximately one-degree display bins, all day/night; separate from the AOI equal-area analysis.'}

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def end_headers(self):
  self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
  script_policy="'self' 'unsafe-inline'" if urlsplit(self.path).path=='/lab' else "'self'"
  self.send_header('Content-Security-Policy',f"default-src 'self'; script-src {script_policy}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
  super().end_headers()
 def send(self,value,status=200,ctype='application/json; charset=utf-8'):
  body=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False).encode() if ctype.startswith('application/json') else value
  self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store' if self.path.startswith('/api') else 'no-cache');self.end_headers()
  try:self.wfile.write(body)
  except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
 def authorized_host(self):
  try:return urlsplit('http://'+self.headers.get('Host','')).hostname in ('localhost','127.0.0.1','::1')
  except ValueError:return False
 def do_GET(self):
  if not self.authorized_host():return self.send({'error':'Loopback Host required'},403)
  try:
   u=urlsplit(self.path);q={k:v[-1] for k,v in parse_qs(u.query).items()}
   if u.path=='/api/health':return self.send({'ok':True,'engine':engine.VERSION})
   if u.path=='/api/earthdata-status':
    import earthdata_access
    return self.send({'configured':earthdata_access.configured(),'storage':'Windows Credential Manager or process environment','token_exposed':False})
   if u.path=='/api/meta':return self.send(metadata())
   if u.path=='/api/places':return self.send(find_places(q.get('q','')[:150]))
   if u.path=='/api/job':
    job=JOBS.get(q.get('id'))
    return self.send(job if job else {'error':'Unknown job'},200 if job else 404)
   if u.path in ('/api/analyze','/api/history','/api/export','/api/overview','/api/sensitivity','/api/pairing'):
    if not QUERY_GATE.acquire(blocking=False):return self.send({'error':'Analysis busy; try again shortly'},429)
    try:
     if u.path=='/api/overview':return self.send(overview(q.get('sensor','noaa20')))
     if u.path=='/api/pairing':return self.send(engine.pairing(DB,engine.scope(q)))
     if u.path=='/api/sensitivity':
      s=engine.scope(q);result=[]
      for grid in (5,10,20):
       h=cached('history',{**s,'grid':grid});m=h.get('model',{})
       result.append({'grid':grid,'state':m.get('state','no_archive'),'regional_factor':m.get('regional_factor'),'metrics':m.get('metrics'),'train_years':m.get('train_years'),'test_years':m.get('test_years'),'run_id':h.get('run_id')})
      return self.send({'results':result,'note':'Sensitivity uses the same historical development data; it is not a fresh independent evaluation.'})
     s=engine.scope(q);kind='history' if u.path=='/api/history' else 'analyze';result=cached(kind,s)
     if u.path!='/api/export':return self.send(result)
     out=io.StringIO(newline='');fields=['id','lat','lon','aqua','target','both','aqua_days','target_days','coverage_state','run_id'];writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader()
     for cell in result['cells']:
      r={k:cell[k] for k in fields if k in cell};r.update(aqua_days='|'.join(cell['aqua_days']),target_days='|'.join(cell['target_days']),coverage_state='unknown',run_id=result['run_id']);writer.writerow(r)
     return self.send(out.getvalue().encode(),ctype='text/csv; charset=utf-8')
    finally:QUERY_GATE.release()
   if u.path=='/':p=STATIC/'index.html'
   elif u.path=='/lab':p=ROOT/'Punjab-Lab.html'
   else:
    p=(STATIC/u.path.lstrip('/')).resolve()
    if not p.is_relative_to(STATIC.resolve()):return self.send({'error':'Not found'},404)
   if not p.is_file():return self.send({'error':'Not found'},404)
   return self.send(p.read_bytes(),ctype=(mimetypes.guess_type(p.name)[0] or 'application/octet-stream')+'; charset=utf-8')
  except (ValueError,TypeError) as e:self.send({'error':str(e)},400)
  except Exception as e:
   print('Request failed:',type(e).__name__,str(e),flush=True);self.send({'error':'Analysis failed. Check the local server log and retry.'},500)
 def do_POST(self):
  if not self.authorized_host():return self.send({'error':'Loopback Host required'},403)
  origin=self.headers.get('Origin')
  if origin and origin not in ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host','')):return self.send({'error':'Same-origin request required'},403)
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send({'error':'JSON required'},415)
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n<1 or n>65536:raise ValueError('Request size must be between 1 and 65536 bytes')
   body=json.loads(self.rfile.read(n))
   if not isinstance(body,dict):raise ValueError('Expected a JSON object')
   if self.path=='/api/archive-plan':return self.send(archive_plan(body))
   if self.path=='/api/archive':return self.send(new_job(archive_plan(body)['items']),202)
   if self.path=='/api/refresh':return self.send(new_job([{'id':p+'-7d.csv','url':url,'product':p,'tier':'nrt','country':'Global'} for p,url in FEEDS.items()]),202)
   if self.path=='/api/cancel':
    j=JOBS.get(body.get('id'))
    if not j:raise ValueError('Unknown job')
    j['cancel']=True;return self.send({'state':'cancel_requested','message':'Stops after the current atomic source finishes.'})
   return self.send({'error':'Unknown endpoint'},404)
  except (ValueError,TypeError) as e:self.send({'error':str(e)},400)
  except Exception as e:print('Job failed:',str(e),flush=True);self.send({'error':'Could not start data job'},500)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8766);args=parser.parse_args()
 if not DB.exists():raise SystemExit('Run python prepare_data.py first.')
 DATA.mkdir(exist_ok=True);engine.initialize(DB);load_places()
 server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True
 print(f'BurnWindow Global · http://127.0.0.1:{args.port} · {len(PLACES):,} searchable places',flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close();POOL.shutdown(wait=False,cancel_futures=True)
