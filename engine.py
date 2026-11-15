"""BurnWindow's reproducible, AOI-local detection-record analysis. No external code runs.

The point products do not contain an observation denominator. A count of zero is
always 'no eligible reports in the loaded file', never verified absence of fire.
"""
from __future__ import annotations
import csv, hashlib, io, json, math, sqlite3, statistics, calendar
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import science

VERSION='global-1.3'
SENSORS=('aqua','terra','snpp','noaa20','noaa21')
LABELS={'aqua':'Aqua MODIS','terra':'Terra MODIS','snpp':'S-NPP VIIRS','noaa20':'NOAA-20 VIIRS','noaa21':'NOAA-21 VIIRS'}
R=6371.0088

class ClosingConnection(sqlite3.Connection):
 def __exit__(self,exc_type,exc_value,traceback):
  try:return super().__exit__(exc_type,exc_value,traceback)
  finally:self.close()

def connect(path):
 c=sqlite3.connect(str(path),timeout=45,factory=ClosingConnection);c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL')
 return c

def initialize(path):
 with connect(path) as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,url TEXT,sha256 TEXT,tier TEXT,country TEXT,product TEXT,start TEXT,end TEXT,retrieved TEXT,rows INTEGER,rejected INTEGER,duplicate_rows INTEGER,bytes INTEGER);
  CREATE TABLE IF NOT EXISTS points(id INTEGER PRIMARY KEY,source TEXT REFERENCES sources(id) ON DELETE CASCADE,sensor TEXT,lat REAL,lon REAL,stamp TEXT,day TEXT,frp REAL,confidence TEXT,daynight TEXT,kind INTEGER,quality INTEGER,UNIQUE(source,sensor,stamp,lat,lon));
  CREATE VIRTUAL TABLE IF NOT EXISTS spatial USING rtree(id,minlat,maxlat,minlon,maxlon);
  CREATE TRIGGER IF NOT EXISTS points_insert AFTER INSERT ON points BEGIN INSERT INTO spatial VALUES(new.id,new.lat,new.lat,new.lon,new.lon); END;
  CREATE TRIGGER IF NOT EXISTS points_delete AFTER DELETE ON points BEGIN DELETE FROM spatial WHERE id=old.id; END;
  CREATE INDEX IF NOT EXISTS points_source ON points(source);
  CREATE INDEX IF NOT EXISTS points_day ON points(day);
  ''')

def platform(row,product):
 p=product.lower();sat=str(row.get('satellite','')).strip().lower()
 if p=='modis':
  if sat in ('a','aqua'):return 'aqua'
  if sat in ('t','terra'):return 'terra'
  raise ValueError('Unrecognized MODIS satellite')
 if p in ('snpp','viirs-snpp'):return 'snpp'
 if p in ('noaa20','viirs-jpss1'):return 'noaa20'
 if p in ('noaa21','viirs-jpss2'):return 'noaa21'
 raise ValueError('Unrecognized product')

def ingest(path,csv_path,meta):
 """Validate an entire source before commit. Updates replace one source atomically."""
 digest=hashlib.sha256(Path(csv_path).read_bytes()).hexdigest()
 with connect(path) as c:
  old=c.execute('SELECT sha256 FROM sources WHERE id=?',(meta['id'],)).fetchone()
  if old and old[0]==digest:return {'unchanged':True,'source':meta['id']}
  c.execute('DELETE FROM sources WHERE id=?',(meta['id'],))
  c.execute('INSERT INTO sources(id,url,sha256,tier,country,product,start,end,retrieved,rows,rejected,duplicate_rows,bytes) VALUES(?,?,?,?,?,?,?,?,?,0,0,0,?)',
    (meta['id'],meta['url'],digest,meta['tier'],meta.get('country','Global'),meta['product'],meta.get('start'),meta.get('end'),meta.get('retrieved',datetime.now(timezone.utc).isoformat()),Path(csv_path).stat().st_size))
  rejected=duplicates=count=0;first=last=None;batch=[]
  with open(csv_path,encoding='utf-8-sig',newline='') as f:
   reader=csv.DictReader(f)
   if not {'latitude','longitude','acq_date','acq_time','confidence','daynight','frp'}<=set(reader.fieldnames or []):raise ValueError('Source is not a FIRMS CSV: missing required columns')
   if meta['tier']=='standard' and 'type' not in reader.fieldnames:raise ValueError('Standard vegetation analysis needs the native type column')
   for row in reader:
    try:
     lat=float(row['latitude']);lon=float(row['longitude']);frp=float(row['frp']);d=date.fromisoformat(row['acq_date'])
     if not all(math.isfinite(x) for x in (lat,lon,frp)) or not -90<=lat<=90 or not -180<=lon<=180 or frp<0:raise ValueError('Invalid coordinates or FRP')
     tm=str(row['acq_time']).zfill(4);dt=datetime(d.year,d.month,d.day,int(tm[:2]),int(tm[2:]),tzinfo=timezone.utc)
     if meta.get('start') and not meta['start']<=d.isoformat()<=meta['end']:raise ValueError('Date outside source contract')
     sensor=platform(row,meta['product']);conf=row['confidence'].lower();conf={'nominal':'n','high':'h','low':'l'}.get(conf,conf);dn=row['daynight'].upper()
     if dn not in ('D','N'):raise ValueError('Invalid day/night flag')
     if sensor in ('aqua','terra'):
      q=float(conf)
      if not math.isfinite(q) or not 0<=q<=100:raise ValueError('Invalid MODIS confidence')
      good=int(q>=30)
     else:
      if conf not in ('l','n','h'):raise ValueError('Invalid VIIRS confidence')
      good=int(conf in ('n','h'))
     kind=int(row['type']) if row.get('type','')!='' else -1
     stamp=dt.isoformat();day=d.isoformat();first=min(first or day,day);last=max(last or day,day)
     batch.append((meta['id'],sensor,lat,lon,stamp,day,frp,conf,dn,kind,good));count+=1
     if len(batch)>=5000:
      before=c.total_changes;c.executemany('INSERT OR IGNORE INTO points(source,sensor,lat,lon,stamp,day,frp,confidence,daynight,kind,quality) VALUES(?,?,?,?,?,?,?,?,?,?,?)',batch);batch=[]
    except (ValueError,KeyError,TypeError):rejected+=1
   c.executemany('INSERT OR IGNORE INTO points(source,sensor,lat,lon,stamp,day,frp,confidence,daynight,kind,quality) VALUES(?,?,?,?,?,?,?,?,?,?,?)',batch)
  # A corrupt download must not silently replace a working source.
  if rejected and rejected/max(1,count+rejected)>.01:raise ValueError(f'{rejected} invalid rows: source rejected atomically')
  actual=c.execute('SELECT count(*) FROM points WHERE source=?',(meta['id'],)).fetchone()[0]
  c.execute('UPDATE sources SET rows=?,rejected=?,duplicate_rows=?,start=COALESCE(start,?),end=COALESCE(end,?) WHERE id=?',(actual,rejected,count-actual,first,last,meta['id']))
 return {'source':meta['id'],'rows':actual,'rejected':rejected,'duplicates':count-actual}

def finite_number(v,lo,hi,name):
 try:n=float(v)
 except (ValueError,TypeError):raise ValueError(f'{name} must be a number')
 if not math.isfinite(n) or not lo<=n<=hi:raise ValueError(f'{name} must be between {lo} and {hi}')
 return n

def scope(params):
 s={'lat':finite_number(params.get('lat',30.90),-90,90,'Latitude'),'lon':finite_number(params.get('lon',75.85),-180,180,'Longitude'),'radius':finite_number(params.get('radius',100),1,1000,'Radius'),'grid':finite_number(params.get('grid',10),5,20,'Grid')}
 if s['grid'] not in (5,10,20):raise ValueError('Grid must be 5, 10, or 20 km')
 s['sensor']=params.get('sensor','noaa20')
 if s['sensor'] not in ('snpp','noaa20','noaa21'):raise ValueError('Choose a VIIRS platform')
 s['daynight']=params.get('daynight','D')
 if s['daynight'] not in ('D','N','all'):raise ValueError('Invalid day/night stratum')
 s['tier']=params.get('tier','nrt')
 if s['tier'] not in ('nrt','standard'):raise ValueError('Invalid data product')
 s['countries']=[x for x in params.get('countries','').split('|') if x]
 if len(s['countries'])>10:raise ValueError('Choose at most ten archive countries per AOI')
 s['start']=date.fromisoformat(params.get('start',(date.today()-timedelta(days=6)).isoformat())).isoformat()
 s['end']=date.fromisoformat(params.get('end',date.today().isoformat())).isoformat()
 if s['end']<s['start']:raise ValueError('End date must follow start date')
 if (date.fromisoformat(s['end'])-date.fromisoformat(s['start'])).days>366:raise ValueError('Map analysis supports at most one year; use Calendar for multi-year history')
 return s

def distance(lat1,lon1,lat2,lon2):
 a,b=map(math.radians,(lat1,lat2));dp=b-a;dl=math.radians(lon2-lon1)
 h=math.sin(dp/2)**2+math.cos(a)*math.cos(b)*math.sin(dl/2)**2
 return 2*R*math.asin(math.sqrt(min(1,max(0,h))))

def bbox(s):
 angle=s['radius']/R;d=math.degrees(angle);lo=max(-90,s['lat']-d);hi=min(90,s['lat']+d)
 if lo<=-90 or hi>=90:return lo,hi,[(-180,180)]
 dl=math.degrees(math.asin(min(1,math.sin(angle)/math.cos(math.radians(s['lat'])))))
 west=s['lon']-dl;east=s['lon']+dl
 if west< -180:return lo,hi,[(west+360,180),(-180,east)]
 if east>180:return lo,hi,[(west,180),(-180,east-360)]
 return lo,hi,[(west,east)]

def cell(lat,lon,grid):
 # Spherical Lambert cylindrical equal-area. The final seam/polar cells are clipped.
 x=int(math.floor(R*math.radians((lon+180)%360)/grid));y=int(math.floor(R*(math.sin(math.radians(lat))+1)/grid))
 return f'{x}:{y}'

def cell_center(key,grid):
 x,y=map(int,key.split(':'));lon=math.degrees(min(2*math.pi*R,(x+.5)*grid)/R)-180
 lat=math.degrees(math.asin(max(-1,min(1,(y+.5)*grid/R-1))))
 return [lat,lon]

def sources_for(c,s):
 rows=[dict(x) for x in c.execute('SELECT * FROM sources WHERE tier=? ORDER BY id',(s['tier'],))]
 if s['tier']=='standard':rows=[x for x in rows if x['country'] in s['countries']]
 return rows

def select_points(c,s,start=None,end=None):
 sources=sources_for(c,s);ids={x['id'] for x in sources}
 lo,hi,ranges=bbox(s);out=[];seen=set();quality_dropped=0
 for west,east in ranges:
  rows=c.execute('''SELECT p.* FROM spatial r CROSS JOIN points p ON p.id=r.id
   WHERE r.minlat<=? AND r.maxlat>=? AND r.minlon<=? AND r.maxlon>=? AND p.day>=? AND p.day<=?''',
   (hi,lo,east,west,start or s['start'],end or s['end']))
  for row in rows:
   if row['source'] not in ids or distance(s['lat'],s['lon'],row['lat'],row['lon'])>s['radius']:continue
   if s['daynight']!='all' and row['daynight']!=s['daynight']:continue
   k=(row['sensor'],row['stamp'],row['lat'],row['lon'])
   if k in seen:continue
   seen.add(k)
   if not row['quality'] or (s['tier']=='standard' and row['kind']!=0):quality_dropped+=1;continue
   out.append(dict(row))
   if len(out)>700000:raise ValueError('Too many reports for an interactive query. Reduce the radius or date range.')
 return out,sources,quality_dropped

def quantile(values,p):
 if not values:return None
 v=sorted(values);i=(len(v)-1)*p;a=int(i);b=min(a+1,len(v)-1)
 return v[a]+(v[b]-v[a])*(i-a)

def available(sources,sensor,start,end,countries=None):
 operating_start={'aqua':'2002-07-04','terra':'2000-11-01','snpp':'2012-01-20','noaa20':'2018-04-01','noaa21':'2024-01-17'}[sensor]
 if start<operating_start:return False
 product={'aqua':'modis','terra':'modis','snpp':'snpp','noaa20':'noaa20','noaa21':'noaa21'}[sensor]
 relevant=[x for x in sources if x['product']==product and x['start'] and x['end']]
 countries=countries or ['Global']
 for country in countries:
  intervals=sorted((x['start'],x['end']) for x in relevant if x['country']==country)
  cursor=date.fromisoformat(start)
  for a,b in intervals:
   if a<=cursor.isoformat()<=b:cursor=date.fromisoformat(b)+timedelta(days=1)
  if cursor<=date.fromisoformat(end):return False
 return True

def analyze(path,s):
 with connect(path) as c:rows,sources,dropped=select_points(c,s)
 daily=defaultdict(lambda:defaultdict(set));cells=defaultdict(lambda:defaultdict(set));frps=defaultdict(list);counts=Counter()
 for r in rows:
  key=cell(r['lat'],r['lon'],s['grid']);sensor=r['sensor'];day=r['day']
  daily[day][sensor].add(key);cells[key][sensor].add(day);frps[sensor].append(r['frp']);counts[sensor]+=1
 a={(d,k) for d,ss in daily.items() for k in ss['aqua']};b={(d,k) for d,ss in daily.items() for k in ss[s['sensor']]};union=a|b;both=a&b
 countries=s['countries'] if s['tier']=='standard' else ['Global']
 series=[];d=date.fromisoformat(s['start']);last=date.fromisoformat(s['end'])
 while d<=last:
  day=d.isoformat();series.append({'date':day,**{ss:len(daily[day][ss]) if available(sources,ss,day,day,countries) else None for ss in SENSORS}});d+=timedelta(days=1)
 stats={ss:{'reports':counts[ss],'cell_days':sum(len(v[ss]) for v in daily.values()),'active_cells':sum(bool(v[ss]) for v in cells.values()),'median_frp':quantile(frps[ss],.5),'p90_frp':quantile(frps[ss],.9),'file_complete':available(sources,ss,s['start'],s['end'],countries)} for ss in SENSORS}
 grid=[]
 for key,v in cells.items():
  if not (v['aqua'] or v[s['sensor']]):continue
  lat,lon=cell_center(key,s['grid']);grid.append({'id':key,'lat':lat,'lon':lon,'aqua':len(v['aqua']),'target':len(v[s['sensor']]),'both':len(v['aqua']&v[s['sensor']]),'days':sorted(v['aqua']|v[s['sensor']]),'aqua_days':sorted(v['aqua']),'target_days':sorted(v[s['sensor']])})
 grid.sort(key=lambda x:(-max(x['aqua'],x['target']),x['id']))
 total=len(a)+len(b);top=sum(x['aqua']+x['target'] for x in grid[:max(1,math.ceil(len(grid)*.1))])
 manifest={'engine':VERSION,'scope':s,'time_basis':'UTC','grid':'spherical Lambert cylindrical equal-area','quality':'MODIS >=30; VIIRS nominal/high; standard type=0','coverage':'unknown: no pixel QA denominator','sources':[{'id':x['id'],'sha256':x['sha256'],'retrieved':x['retrieved']} for x in sources]}
 run_id=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:16]
 return {'run_id':run_id,'scope':s,'stats':stats,'series':series,'cells':grid,'map_truncated':False,'overlap':{'both':len(both),'aqua_only':len(a-b),'target_only':len(b-a),'union':len(union),'jaccard':len(both)/len(union) if union else None},'concentration':top/total if total else None,'quality_excluded':dropped,'sources':sources,'manifest':manifest,'coverage':'unknown','calibration':'Local historical fit required; provisional feeds are not converted by archive factors.'}

def metrics(pairs):
 # Each tuple is observed comparator, estimate; zero comparator totals have no percentage metric.
 n=len(pairs);den=sum(a for a,b in pairs);err=sum(abs(a-b) for a,b in pairs)
 return {'n':n,'wape':100*err/den if den else None,'bias':100*sum(b-a for a,b in pairs)/den if den else None,'mae':err/n if n else None}

def historical(path,s):
 hs={**s,'tier':'standard'}
 with connect(path) as c:
  sources=sources_for(c,hs)
  years=sorted({int(x['start'][:4]) for x in sources if x['start']})
  if not years:return {'state':'no_archive','reason':'Load standard country archives for this area in Data & evidence.','years':[],'months':[]}
  rows,sources,dropped=select_points(c,hs,f'{min(years)}-01-01',f'{max(years)}-12-31')
 monthly=defaultdict(set);byday=defaultdict(set)
 for r in rows:
  key=cell(r['lat'],r['lon'],s['grid']);monthly[(r['sensor'],int(r['day'][:4]),int(r['day'][5:7]))].add((r['day'],key));byday[(r['sensor'],r['day'])].add(key)
 def complete(sensor,y,m):return available(sources,sensor,f'{y}-{m:02d}-01',f'{y}-{m:02d}-{calendar.monthrange(y,m)[1]}',s['countries'])
 def count(sensor,y,m):return len(monthly[sensor,y,m]) if complete(sensor,y,m) else None
 paired=[y for y in years if all(complete(ss,y,m) for ss in ('aqua',s['sensor']) for m in range(1,13))]
 # Last two fully available years are always evaluation-only. Never refit on them.
 train=paired[:-2];test=paired[-2:] if len(paired)>=2 else []
 # Historical context can use older Aqua years even when VIIRS did not exist.
 baseline_years=[y for y in years if test and y<min(test) and all(complete('aqua',y,m) for m in range(1,13))]
 ratios=[sum(count('aqua',y,m) for m in range(1,13))/sum(count(s['sensor'],y,m) for m in range(1,13)) for y in train if sum(count(s['sensor'],y,m) for m in range(1,13))>0]
 enough=len(train)>=3 and len(test)>=2 and len(ratios)>=3 and sum(count('aqua',y,m) for y in train for m in range(1,13))>=30
 factor=statistics.median(ratios) if enough else None
 factors={};support={};stability={}
 if enough:
  for m in range(1,13):
   local=[count('aqua',y,m)/count(s['sensor'],y,m) for y in train if count(s['sensor'],y,m)>0]
   n=len(local);w=n/(n+4);factors[m]=w*statistics.median(local)+(1-w)*factor if n>=3 else factor;support[m]=n
   deleted=[statistics.median(local[:i]+local[i+1:]) for i in range(n)] if n>=3 else []
   stability[m]=[min(deleted),max(deleted)] if deleted else None
 months=[];raw=[];regional=[];pooled=[];errors=[];per_year=[]
 for y in years:
  for m in range(1,13):
   a=count('aqua',y,m);b=count(s['sensor'],y,m)
   baseline=[count('aqua',t,m) for t in baseline_years if count('aqua',t,m) is not None]
   p90=quantile(baseline,.9) if len(baseline)>=3 else None
   estimate=b*factors[m] if b is not None and enough else None
   row={'year':y,'month':m,'aqua':a,'target':b,'estimate':estimate,'p90':p90,'median':quantile(baseline,.5) if baseline else None,'split':'test' if y in test else 'train' if y in train else 'unpaired','factor':factors.get(m),'support':support.get(m,0)}
   months.append(row)
   if y in test and a is not None and b is not None and enough:
    raw.append((a,b));regional.append((a,b*factor));pooled.append((a,estimate))
    if p90 is not None and ((a>p90)!=(estimate>p90)):errors.append({**row,'type':'Missed high' if a>p90 else 'Excess high'})
 for y in test:
  rr=[x for x in months if x['year']==y and x['aqua'] is not None and x['estimate'] is not None]
  peaks={k:max(rr,key=lambda x:x[k])['month'] if rr and sum(x[k] for x in rr)>0 else None for k in ('aqua','target','estimate')}
  displacement=min(abs(peaks['aqua']-peaks['estimate']),12-abs(peaks['aqua']-peaks['estimate'])) if peaks['aqua'] and peaks['estimate'] else None
  per_year.append({'year':y,'raw':metrics([(x['aqua'],x['target']) for x in rr]),'pooled':metrics([(x['aqua'],x['estimate']) for x in rr]),'peak_months':peaks,'peak_displacement_months':displacement})
 model_metrics={'raw':metrics(raw),'regional':metrics(regional),'pooled':metrics(pooled)}
 season=[]
 # Independent annual UTC calendars; no hemisphere-specific season is imposed.
 for y in years:
  if not all(complete('aqua',y,m) for m in range(1,13)):continue
  ds=[];d=date(y,1,1)
  while d.year==y:ds.append((d.isoformat(),len(byday['aqua',d.isoformat()])));d+=timedelta(days=1)
  total=sum(v for _,v in ds)
  if not total:season.append({'year':y,'total':0,'onset':None,'end':None,'peak_start':None,'peak_end':None});continue
  cumulative=0;onset=end=None
  for day,v in ds:
   cumulative+=v
   if onset is None and cumulative>=total*.1:onset=day
   if end is None and cumulative>=total*.9:end=day
  rolling=[sum(v for _,v in ds[i:i+31]) for i in range(len(ds)-30)];i=max(range(len(rolling)),key=rolling.__getitem__)
  season.append({'year':y,'total':total,'onset':onset,'end':end,'peak_start':ds[i][0],'peak_end':ds[i+30][0],'peak_share':rolling[i]/total})
 confusion=Counter()
 for r in months:
  if r['year'] in test and r['aqua'] is not None and r['estimate'] is not None and r['p90'] is not None:
   observed=r['aqua']>r['p90'];predicted=r['estimate']>r['p90'];confusion['both_high' if observed and predicted else 'missed_high' if observed else 'excess_high' if predicted else 'both_not_high']+=1
 model={'state':'evaluated' if enough else 'insufficient','train_years':train,'test_years':test,'regional_factor':factor,'monthly_factors':factors,'support':support,'year_deletion_ratio_range':stability,'confusion':dict(confusion),'metrics':model_metrics,'per_year':per_year,'disagreements':errors,'protocol':'Last two complete paired years held out; >=3 earlier fit years and >=30 Aqua cell-days; median annual ratio; monthly median shrunk n/(n+4) toward regional; >=3 positive-target years per month or regional fallback. No automatic model promotion.'}
 model['baseline_years']=baseline_years
 model['science']=science.diagnostic(months,train,test,baseline_years=baseline_years) if enough else {'state':'insufficient'}
 contract={'engine':VERSION,'scope':{k:v for k,v in hs.items() if k not in ('start','end')},'sources':[{'id':x['id'],'sha256':x['sha256']} for x in sources],'model':model['protocol'],'scientific_checks':science.PROTOCOL,'train':train,'test':test,'aqua_baseline_years':baseline_years}
 return {'state':'ready','run_id':hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()[:16],'years':years,'months':months,'model':model,'season':season,'sources':sources,'manifest':contract,'quality_excluded':dropped,'coverage':'Point-report archive; observed-negative denominator unavailable. Annual clocks can split a cross-year fire season.'}

def pairing(path,s):
 with connect(path) as c:rows,sources,_=select_points(c,s)
 result=science.associations(rows,s['sensor'])
 result['scope']=s;result['sources']=[{'id':r['id'],'sha256':r['sha256']} for r in sources]
 result['run_id']=hashlib.sha256(json.dumps({'engine':VERSION,'scope':s,'sources':result['sources'],'protocol':science.PROTOCOL},sort_keys=True).encode()).hexdigest()[:16]
 return result
