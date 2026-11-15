"""Training-only diagnostics for a detection-record transfer, not a physical fire model.

No hyperparameter is selected using the displayed final evaluation years. Whole
training years are resampled together so monthly covariance is retained. Bootstrap
bands quantify sensitivity to the sampled training years; they are not prediction
intervals and omit observation/label uncertainty.
"""
from __future__ import annotations
import math, random, statistics, hashlib, json
from collections import defaultdict
from datetime import datetime

PROTOCOL='science-v2.2: expanding-origin; 400 training-year bootstrap draws; pre-test Aqua-only historical reference; conservative rank fractions; threshold-disagreement review; 1km/5,15,30min point associations'

def quantile(values,p):
 if not values:return None
 v=sorted(values);f=(len(v)-1)*p;i=int(f);j=min(i+1,len(v)-1)
 return v[i]+(v[j]-v[i])*(f-i)

def fit(months,years):
 """Duplicate years in `years` are intentional bootstrap blocks."""
 lookup={(r['year'],r['month']):r for r in months}
 blocks=[[lookup.get((y,m)) for m in range(1,13)] for y in years]
 if len(blocks)<3 or any(any(r is None or r['aqua'] is None or r['target'] is None for r in b) for b in blocks):return None
 totals=[(sum(r['aqua'] for r in b),sum(r['target'] for r in b)) for b in blocks]
 ratios=[a/b for a,b in totals if b>0]
 if len(ratios)<3 or sum(a for a,b in totals)<30:return None
 annual=statistics.median(ratios);factors={}
 for m in range(1,13):
  local=[b[m-1]['aqua']/b[m-1]['target'] for b in blocks if b[m-1]['target']>0]
  n=len(local);w=n/(n+4)
  factors[m]=w*statistics.median(local)+(1-w)*annual if n>=3 else annual
 return {'annual':annual,'monthly':factors}

def score(rows,model,method):
 pairs=[(r['aqua'],r['target'] if method=='raw' else r['target']*model['annual'] if method=='regional' else r['target']*model['monthly'][r['month']]) for r in rows if r['aqua'] is not None and r['target'] is not None]
 den=sum(a for a,b in pairs);n=len(pairs);errors=[b-a for a,b in pairs]
 return {'n':n,'wape':sum(abs(e) for e in errors)/den*100 if den else None,'bias':sum(errors)/den*100 if den else None,'mae':sum(abs(e) for e in errors)/n if n else None}

def empirical_tail(reference,value):
 if not reference or value is None:return None
 return (1+sum(x>=value for x in reference))/(len(reference)+1)

def diagnostic(months,train,test,draws=400,baseline_years=None):
 baseline_years=train if baseline_years is None else baseline_years
 all_years=sorted(set(train+test));folds=[]
 for year in all_years:
  earlier=[y for y in all_years if y<year]
  if len(earlier)<3:continue
  fitted=fit(months,earlier)
  if not fitted:continue
  rows=[r for r in months if r['year']==year]
  folds.append({'year':year,'train_years':earlier,'use':'development' if year in train else 'final-window replay','metrics':{k:score(rows,fitted,k) for k in ('raw','regional','pooled')}})
 final=fit(months,train)
 if final is None:return {'state':'insufficient','rolling_folds':folds,'protocol':PROTOCOL}
 # Seed is independent of final-year outcomes. Altering test labels cannot move fit bands.
 training_rows=[{k:r[k] for k in ('year','month','aqua','target')} for r in months if r['year'] in train]
 seed=int(hashlib.sha256(json.dumps(sorted(training_rows,key=lambda r:(r['year'],r['month'])),sort_keys=True).encode()).hexdigest()[:16],16)
 rng=random.Random(seed);samples=[]
 for _ in range(draws):
  selected=[rng.choice(train) for _ in train];fitted=fit(months,selected)
  if fitted:samples.append(fitted)
 bands={m:[quantile([f['monthly'][m] for f in samples],.05),quantile([f['monthly'][m] for f in samples],.95)] for m in range(1,13)}
 evaluations=[]
 for r in months:
  if r['year'] not in test or r['target'] is None or r['aqua'] is None:continue
  m=r['month'];ref=[x['aqua'] for x in months if x['year'] in baseline_years and x['month']==m and x['aqua'] is not None]
  p90=quantile(ref,.9);est=r['target']*final['monthly'][m];low,high=bands[m]
  lo=r['target']*low if low is not None else None;hi=r['target']*high if high is not None else None
  crossing=lo is not None and p90 is not None and lo<=p90<hi
  disagreement=p90 is not None and ((r['aqua']>p90)!=(est>p90))
  reasons=[]
  if crossing:reasons.append('Fit band crosses P90')
  if len(ref)<9:reasons.append('Fewer than 9 annual reference values')
  if disagreement:reasons.append('Aqua and estimate disagree at P90')
  evaluations.append({'year':r['year'],'month':m,'aqua':r['aqua'],'estimate':est,'fit_band':[lo,hi],'p90':p90,'reference_years':len(ref),'minimum_rank_fraction':1/(len(ref)+1),'aqua_upper_rank_fraction':empirical_tail(ref,r['aqua']),'estimate_upper_rank_fraction':empirical_tail(ref,est),'band_crosses_p90':crossing,'comparator_disagreement':disagreement,'review':bool(reasons),'review_reason':'; '.join(reasons) if reasons else 'No flag in these checks; observation coverage remains unknown'})
 valid=[r for r in evaluations if r['fit_band'][0] is not None]
 inside=sum(r['fit_band'][0]<=r['aqua']<=r['fit_band'][1] for r in valid)
 ratios=[]
 for y in test:
  rows=[r for r in months if r['year']==y and r['aqua'] is not None and r['target'] is not None];a=sum(r['aqua'] for r in rows);b=sum(r['target'] for r in rows)
  actual=a/b if b else None
  ratios.append({'year':y,'observed_ratio':actual,'training_ratio':final['annual'],'relative_change_pct':100*(actual/final['annual']-1) if actual is not None and final['annual'] else None})
 return {'state':'ready','protocol':PROTOCOL,'bootstrap':{'training_years':len(train),'requested':draws,'valid':len(samples),'unit':'entire training year','central_fraction':.9,'seed':str(seed),'monthly_factor_bands':bands,'note':'5th–95th percentiles of training-year refits. Sensitivity bands, not confidence or prediction intervals. Clouds, missed fires and other sensor errors are excluded.'},'rolling_folds':folds,'evaluation':evaluations,'reference_resolution':{'years':len(baseline_years),'baseline_years':baseline_years,'minimum_rank_fraction':1/(len(baseline_years)+1),'upper_decile_resolvable':len(baseline_years)>=9},'fit_band_check':{'inside':inside,'n':len(valid),'fraction':inside/len(valid) if valid else None,'note':'Descriptive containment of the Aqua comparator; no nominal prediction coverage is claimed.'},'drift':ratios,'review_months':sum(x['review'] for x in evaluations)}

def associations(rows,sensor,max_rows=100000):
 """Many-to-many nearby point centres; no footprint/negative class inference.

Cartesian spatial bins avoid longitude-wrap and polar-neighbor mistakes. A chord
distance <=1 km implies a Cartesian coordinate difference <=1 km on every axis,
so the 27 neighboring bins contain every candidate inside the great-circle gate.
"""
 aqua=[r for r in rows if r['sensor']=='aqua'];target=[r for r in rows if r['sensor']==sensor]
 if len(aqua)+len(target)>max_rows:return {'state':'too_large','reason':'Reduce the period or radius below 100,000 selected Aqua + VIIRS reports.'}
 def xyz(r):
  lat=math.radians(r['lat']);lon=math.radians(r['lon']);return (6371.0088*math.cos(lat)*math.cos(lon),6371.0088*math.cos(lat)*math.sin(lon),6371.0088*math.sin(lat))
 def stamp(r):return datetime.fromisoformat(r['stamp']).timestamp()
 bins=defaultdict(list);target_times=[]
 for j,r in enumerate(target):
  t=stamp(r);target_times.append(t);x,y,z=xyz(r);bins[(math.floor(t/1800),math.floor(x),math.floor(y),math.floor(z))].append(j)
 matches={m:{'aqua':set(),'target':set(),'edges':0,'minutes':[],'distances':[]} for m in (5,15,30)};examples=[]
 for i,r in enumerate(aqua):
  t=stamp(r);tbin=math.floor(t/1800);rx,ry,rz=xyz(r);ix,iy,iz=map(math.floor,(rx,ry,rz))
  for dt in (-1,0,1):
   for dx in (-1,0,1):
    for dy in (-1,0,1):
     for dz in (-1,0,1):
      for j in bins.get((tbin+dt,ix+dx,iy+dy,iz+dz),()):
       v=target[j];minutes=abs(t-target_times[j])/60
       if minutes>30 or r['daynight']!=v['daynight']:continue
       vx,vy,vz=xyz(v);chord=math.sqrt((rx-vx)**2+(ry-vy)**2+(rz-vz)**2);distance=2*6371.0088*math.asin(min(1,chord/(2*6371.0088)))
       if distance>1:continue
       if matches[30]['edges']>=250000:return {'state':'too_large','reason':'More than 250,000 candidate associations. Reduce the date range or radius.'}
       for window,m in matches.items():
        if minutes<=window:m['aqua'].add(i);m['target'].add(j);m['edges']+=1;m['minutes'].append(minutes);m['distances'].append(distance)
       if len(examples)<20:examples.append({'aqua_stamp':r['stamp'],'viirs_stamp':v['stamp'],'aqua_lat':r['lat'],'aqua_lon':r['lon'],'viirs_lat':v['lat'],'viirs_lon':v['lon'],'distance_km':round(distance,4),'minutes':round(minutes,2)})
 windows=[]
 for window,m in matches.items():windows.append({'minutes':window,'distance_km':1,'aqua_matched':len(m['aqua']),'aqua_total':len(aqua),'target_matched':len(m['target']),'target_total':len(target),'edges':m['edges'],'aqua_fraction':len(m['aqua'])/len(aqua) if aqua else None,'target_fraction':len(m['target'])/len(target) if target else None,'median_minutes':statistics.median(m['minutes']) if m['minutes'] else None,'median_distance_km':statistics.median(m['distances']) if m['distances'] else None})
 return {'state':'ready','windows':windows,'examples':examples,'method':'Many-to-many point centres within 1 km great-circle distance, same day/night stratum, absolute UTC time difference <=5/15/30 min. Both records must fall in the requested calendar window. Window edges may censor partners.','interpretation':'Association consistency, not recall, precision, omission error, or proof of the same fire. Positive-only files lack clear-land non-fire observations.'}
