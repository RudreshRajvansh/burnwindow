"""Reproducible, fixed-protocol evidence evaluation. Never fits on geographic targets.

CLI dependencies for event matching: numpy, shapely, pyproj. Geographic scoring is
stdlib-only. Point associations against MTBS corroborate mapped events; they do not
estimate pixel-level accuracy, true ignition delay, or burned area.
"""
from pathlib import Path
from datetime import date,datetime,timezone
from collections import defaultdict
import csv,json,math,hashlib,sys,importlib.util,argparse

BASE=Path(__file__).resolve().parent;V=BASE/'data/validation'

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def read_protocol(directory=V):
 p=directory/'protocol.json';expected=(directory/'protocol.sha256').read_text().split()[0]
 if digest(p)!=expected:raise ValueError('Frozen protocol hash mismatch')
 doc=json.loads(p.read_text())
 for name,want in doc['code_sha256'].items():
  if digest(directory/'frozen_code'/name)!=want:raise ValueError('Frozen analysis code hash mismatch')
 return doc,expected

def native_rows(path,product,year,audit=None):
 """Validate native fields before selecting quality/type; no implicit missing zeros."""
 audit=audit if audit is not None else {};audit.update(read=0,rejected=0,eligible=0)
 with Path(path).open(encoding='utf-8-sig',newline='') as f:
  reader=csv.DictReader(f)
  if not {'latitude','longitude','acq_date','acq_time','confidence','daynight','type','frp'}<=set(reader.fieldnames or []):raise ValueError('Required standard-product fields missing')
  for row in reader:
   audit['read']+=1
   try:
    lat=float(row['latitude']);lon=float(row['longitude']);frp=float(row['frp']);day=date.fromisoformat(row['acq_date']);tm=row['acq_time'].zfill(4)
    if not all(map(math.isfinite,[lat,lon,frp])) or not -90<=lat<=90 or not -180<=lon<=180 or frp<0 or day.year!=year:raise ValueError()
    dt=datetime(day.year,day.month,day.day,int(tm[:2]),int(tm[2:]),tzinfo=timezone.utc);dn=row['daynight'].upper()
    if dn not in ('D','N'):raise ValueError()
    kind=int(row['type']);conf=row['confidence'].lower();conf={'nominal':'n','high':'h','low':'l'}.get(conf,conf)
    if product=='modis':
     q=float(conf);sat=row.get('satellite','').lower()
     if not math.isfinite(q) or not 0<=q<=100 or sat not in ('a','aqua','t','terra'):raise ValueError()
     sensor='aqua' if sat in ('a','aqua') else 'terra';good=q>=30
    else:
     if conf not in ('l','n','h'):raise ValueError()
     sensor=product;good=conf in ('n','h')
   except (ValueError,TypeError,KeyError):audit['rejected']+=1;continue
   if good and kind==0 and sensor!='terra':
    audit['eligible']+=1;yield {'lat':lat,'lon':lon,'day':day.isoformat(),'month':day.month,'year':day.year,'stamp':dt.isoformat(),'daynight':dn,'sensor':sensor}
 if audit['rejected']/max(audit['read'],1)>.01:raise ValueError('More than 1% malformed source rows; source failed')

def error_metrics(pairs):
 pairs=list(pairs);den=sum(a for a,b in pairs);n=len(pairs);err=[b-a for a,b in pairs]
 return {'n':n,'aqua_total':den,'estimate_total':sum(b for a,b in pairs),'wape':100*sum(abs(e) for e in err)/den if den else None,'bias':100*sum(err)/den if den else None,'mae':sum(abs(e) for e in err)/n if n else None}

def predict(target,fitted,month):
 return {'raw':target,'annual':target*fitted['annual'],'pooled':target*fitted['monthly'][str(month)]}

def peak_displacement(rows,method):
 if not rows or not sum(r['aqua'] for r in rows) or not sum(r[method] for r in rows):return None
 a=max(rows,key=lambda r:r['aqua'])['month'];b=max(rows,key=lambda r:r[method])['month'];return min(abs(a-b),12-abs(a-b))

def seal_result(name,result,protocol_hash):
 path=V/(name+'.json')
 if path.exists():raise ValueError('Results already scored; refusing to overwrite first-look evidence')
 result.update(protocol_sha256=protocol_hash,scored_at_utc=datetime.now(timezone.utc).isoformat(),evaluator_sha256=digest(__file__))
 # Exclusive create prevents accidental replacement of the initial evaluation.
 with path.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
 (V/(name+'.sha256')).write_text(digest(path)+'  '+path.name+'\n')

def geographic(cache):
 p,ph=read_protocol();snapshot=V/'frozen_code';sys.path.insert(0,str(snapshot))
 spec=importlib.util.spec_from_file_location('frozen_engine',snapshot/'engine.py');e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
 manifest={r['id']:r for r in json.loads((V/'download-manifest.json').read_text())};counts={};sources=[];failures={}
 for source in p['target_files']:
  path=cache/source['id'];meta=manifest[source['id']];audit={};region=next(r for r in p['heldout_regions'] if r['country']==source['country'])
  try:
   if 'error' in meta or digest(path)!=meta['sha256']:raise ValueError('Source missing or SHA-256 mismatch')
   seen=defaultdict(set)
   for r in native_rows(path,source['product'],source['year'],audit):
    if abs(r['lat']-region['lat'])>1:continue
    if e.distance(r['lat'],r['lon'],region['lat'],region['lon'])>p['radius_km']:continue
    seen[(r['daynight'],r['month'])].add((r['day'],e.cell(r['lat'],r['lon'],p['grid_km'])))
   for dn in p['strata']:
    for month in range(1,13):counts[(source['country'],source['product'],source['year'],dn,month)]=len(seen[dn,month])
   sources.append({**meta,'audit':audit})
  except Exception as exc:failures[source['id']]=str(exc)
  print('Parsed target source',source['id'],flush=True)
 cases=[]
 for region in p['heldout_regions']:
  for sensor in p['platforms']:
   for dn in p['strata']:
    fitted=p['models'][sensor+':'+dn]['fit'];rows=[];missing=[]
    for year in p['test_years']:
     for month in range(1,13):
      a=counts.get((region['country'],'modis',year,dn,month));b=counts.get((region['country'],sensor,year,dn,month))
      if a is None or b is None:missing.append(f'{year}-{month:02d}');continue
      rows.append({'year':year,'month':month,'aqua':a,'target':b,**predict(b,fitted,month)})
    status='incomplete' if missing else 'scored';metrics={k:error_metrics((r['aqua'],r[k]) for r in rows) for k in ('raw','annual','pooled')}
    cases.append({'region':region,'sensor':sensor,'daynight':dn,'state':status,'months':rows,'missing_months':missing,'metrics':metrics,'peak_displacement':[{'year':year,**{k:peak_displacement([r for r in rows if r['year']==year],k) for k in ('raw','annual','pooled')}} for year in p['test_years']]})
 seal_result('geographic',{'title':'Frozen first-look geographic transfer','cases':cases,'sources':sources,'source_failures':failures,'interpretation':'No target-area calibration. Models pool source-area annual counts before fitting. First-look locally frozen test, not externally blinded. Four selected areas do not establish global validity; after inspection this dataset is evaluation evidence, not an untouched future test.'},ph)
 print('GEOGRAPHIC SEALED:',len(cases),'cases',flush=True)

def corroborate(cache):
 import numpy as np
 from shapely.geometry import shape
 from shapely.ops import transform
 from shapely import contains_xy,intersects_xy,make_valid
 from pyproj import Transformer
 p,ph=read_protocol();ref=json.loads((V/'mtbs-reference.geojson').read_text());rm=json.loads((V/'mtbs-manifest.json').read_text());assert digest(V/'mtbs-reference.geojson')==rm['sha256']
 features=ref['features'];bounds=[shape(f['geometry']).bounds for f in features];box=(min(b[0] for b in bounds)-.03,min(b[1] for b in bounds)-.03,max(b[2] for b in bounds)+.03,max(b[3] for b in bounds)+.03)
 pts=[];sources=[]
 for meta in json.loads((V/'download-manifest.json').read_text()):
  if meta['year']!=2023 or meta['country']!='United_States':continue
  path=cache/meta['id'];assert digest(path)==meta['sha256'];audit={};unique=set()
  for r in native_rows(path,meta['product'],2023,audit):
   if box[0]<=r['lon']<=box[2] and box[1]<=r['lat']<=box[3]:
    key=(r['sensor'],r['stamp'],r['lat'],r['lon'])
    if key not in unique:pts.append(r);unique.add(key)
  sources.append({**meta,'audit':audit});print('Parsed independent-point source',meta['id'],flush=True)
 lon=np.array([r['lon'] for r in pts]);lat=np.array([r['lat'] for r in pts]);day=np.array([date.fromisoformat(r['day']).toordinal() for r in pts]);sensor=np.array([r['sensor'] for r in pts]);dn=np.array([r['daynight'] for r in pts]);events=[]
 for f in features:
  a=f['properties'];event={'id':a['fire_id'],'name':a['fire_name'],'attributes':a,'cases':[]}
  try:
   ignition=date(int(a['year']),int(a['startmonth']),int(a['startday']));geom=make_valid(shape(f['geometry']));cent=geom.centroid
   local=Transformer.from_crs('EPSG:4326',f'+proj=aeqd +lat_0={cent.y} +lon_0={cent.x} +datum=WGS84 +units=m',always_xy=True)
   pg=transform(local.transform,geom);x,y=local.transform(lon,lat);age=day-ignition.toordinal()
   event.update(ignition=ignition.isoformat(),centroid=[cent.x,cent.y],state='scored')
   for km in p['independent_validation']['distance_buffers_km']:
    inside=intersects_xy(pg.buffer(km*1000) if km else pg,x,y)
    for ss in p['independent_validation']['sensors']:
     for dd in ['D','N']:
      select=inside&(sensor==ss)&(dn==dd);post=select&(age>=0)&(age<60)
      event['cases'].append({'buffer_km':km,'sensor':ss,'daynight':dd,'counts':{str(w):int(np.sum(select&(age>=0)&(age<w))) for w in [7,30,60]},'first_report_day_offset':int(age[post].min()) if post.any() else None,'pre_ignition_7day_reports':int(np.sum(select&(age>=-7)&(age<0)))})
  except Exception as exc:event.update(state='reference_error',error=str(exc))
  events.append(event)
 summary=[]
 for ss in ['aqua','snpp','noaa20']:
  for dd in ['D','N']:
   for km in [0,1]:
    for window in [7,30,60]:
     cases=[next(c for c in e['cases'] if c['sensor']==ss and c['daynight']==dd and c['buffer_km']==km) for e in events if e['state']=='scored']
     n=len(cases);hit=sum(c['counts'][str(window)]>0 for c in cases)
     summary.append({'sensor':ss,'daynight':dd,'buffer_km':km,'window_days':window,'events_with_reports':hit,'evaluated_events':n,'selected_events':len(events),'fraction':hit/n if n else None})
 seal_result('independent',{'title':'Independent MTBS event corroboration','events':events,'summary':summary,'sources':sources,'reference_manifest':rm,'spatial_filter_bounds':box,'candidate_reports':len(pts),'interpretation':'Mapped-event corroboration only. A report inside the eventual burned perimeter is not proof it detected that specific event. Reference dates are day-resolution, windows are [ignition, ignition + N days), incomplete/small/unmapped fires are not negatives, and no precision/recall or true detection-latency claim is made.'},ph)
 print('INDEPENDENT SEALED:',len(events),'selected events',flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['geographic','independent']);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--deps',type=Path);args=parser.parse_args()
 if args.deps:sys.path.insert(0,str(args.deps.resolve()))
 if (V/(args.kind+'.json')).exists():raise SystemExit('Result already sealed; preserved without re-scoring.')
 (geographic if args.kind=='geographic' else corroborate)(args.cache)
