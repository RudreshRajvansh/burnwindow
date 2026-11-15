"""Decode authenticated native Aqua MYD14.061 + MYD03.061 files after download.

Not used to generate the public NOAA evidence. This route remains unverified on
real NASA inputs until the user's Earthdata downloads succeed. MODIS class 2 is
unprocessed, never the NOAA sun-glint meaning. Raw algorithm QA is retained and
not decoded using NOAA bit positions.
"""
from pathlib import Path
import json,os,argparse,sys
from datetime import datetime,timezone
from validate_evidence import digest

NAMES=['missing_input','obsolete_unprocessed','other_unprocessed','nonfire_water','cloud','nonfire_land','unknown','low_fire','nominal_fire','high_fire','unknown_code']

def process(cache,output,filename='aqua-coverage.json'):
 import numpy as np
 from pyhdf.SD import SD,SDC
 plan=json.loads((output/'aqua-download-plan.json').read_text());manifest={r['file']:r for r in json.loads((cache/'manifest.json').read_text())};records=[];totals=np.zeros(11,dtype='int64');cropdir=output/'aqua-pixel-evidence';cropdir.mkdir(exist_ok=True)
 for pair in plan['pairs']:
  fpath=cache/pair['mask'];gpath=cache/pair['geolocation'];record={'mask_file':fpath.name,'geolocation_file':gpath.name,'state':'unverified'};fh=gh=None
  try:
   for path in (fpath,gpath):
    if digest(path)!=manifest[path.name]['sha256']:raise ValueError('Native file checksum mismatch')
   if not fpath.name.startswith('MYD14.') or not gpath.name.startswith('MYD03.') or '.061.' not in fpath.name or '.061.' not in gpath.name or fpath.name.split('.')[1:3]!=gpath.name.split('.')[1:3]:raise ValueError('Acquisition, collection or platform mismatch')
   fh=SD(str(fpath),SDC.READ);gh=SD(str(gpath),SDC.READ)
   if gpath.name not in str(fh.attributes().get('MOD03 input file','')):raise ValueError('Geolocation is not the exact MOD03 input named by MYD14')
   mask=fh.select('fire mask')[:];lat=gh.select('Latitude')[:];lon=gh.select('Longitude')[:]
   if mask.shape!=lat.shape or mask.shape!=lon.shape or mask.ndim!=2:raise ValueError('Native geolocation dimensions do not match the fire mask')
   if mask.dtype.kind not in 'ui':raise ValueError('Unexpected mask encoding')
   keys=fh.datasets();diff=[]
   if all(k in keys for k in ['FP_line','FP_sample','FP_latitude','FP_longitude']) and all(np.prod(np.atleast_1d(fh.select(k).info()[2]))>0 for k in ['FP_line','FP_sample','FP_latitude','FP_longitude']):
    rr=fh.select('FP_line')[:].astype(int);cc=fh.select('FP_sample')[:].astype(int);fl=fh.select('FP_latitude')[:];fo=fh.select('FP_longitude')[:]
    good=(rr>=0)&(rr<mask.shape[0])&(cc>=0)&(cc<mask.shape[1])&(abs(fl)<=90)&(abs(fo)<=180)
    diff=np.maximum(abs(lat[rr[good],cc[good]]-fl[good]),abs((lon[rr[good],cc[good]]-fo[good]+180)%360-180)).tolist()
    if diff and max(diff)>1e-3:raise ValueError('Sparse fire locations disagree with full geolocation')
   valid=np.isfinite(lat)&np.isfinite(lon)&(abs(lat)<=90)&(abs(lon)<=180);w,s,e,n=plan['bbox'];inside=valid&(lat>=s)&(lat<=n)&(lon>=w)&(lon<=e)
   raw=mask[inside];values=np.where(raw<=9,raw,10);counts=np.bincount(values,minlength=11);payload={'latitude':lat[inside],'longitude':lon[inside],'fire_mask':raw}
   if 'algorithm QA' in keys:payload['raw_algorithm_qa']=fh.select('algorithm QA')[:][inside]
   evidence=cropdir/(fpath.name+'.npz');np.savez_compressed(evidence,**payload)
   record.update(state='decoded_native_samples',counts=dict(zip(NAMES,map(int,counts))),pixel_samples=int(counts.sum()),native_shape=list(mask.shape),alignment_checks=len(diff),max_alignment_error_degrees=max(diff,default=None),pixel_evidence={'file':'aqua-pixel-evidence/'+evidence.name,'sha256':digest(evidence)},sources=[manifest[fpath.name],manifest[gpath.name]])
   totals+=counts
  except Exception as exc:record['reason']=str(exc)
  finally:
   if fh:fh.end()
   if gh:gh.end()
  records.append(record);print(fpath.name,record['state'],record.get('pixel_samples',''),flush=True)
 result={'product':'Aqua MYD14.061 + MYD03.061','date':plan['date'],'bbox':plan['bbox'],'granules':records,'counts':dict(zip(NAMES,map(int,totals))),'pixel_samples':int(totals.sum()),'all_selected_decoded':all(r['state']=='decoded_native_samples' for r in records),'interpretation':'Native geolocated product-class samples only. Cloud and nonfire labels are product observations, not independently verified cloud/fire truth. Full-area/day coverage and pixel-area weighting are not established. Raw MODIS QA is not interpreted with NOAA bit meanings.','processed_at_utc':datetime.now(timezone.utc).isoformat()}
 with (output/filename).open('x') as f:json.dump(result,f,indent=2)
 (output/(filename+'.sha256')).write_text(digest(output/filename)+'  '+filename+'\n')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,default=Path(os.environ.get('LOCALAPPDATA','.'))/'BurnWindow'/'earthdata-cache');p.add_argument('--deps',type=Path);p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'data/validation');p.add_argument('--result-name',default='aqua-coverage.json');a=p.parse_args()
 if a.deps:sys.path.insert(0,str(a.deps.resolve()))
 if Path(a.result_name).name!=a.result_name or not a.result_name.endswith('.json'):raise SystemExit('Use a simple JSON filename')
 if (a.output/a.result_name).exists():raise SystemExit('Aqua evidence exists; refusing to overwrite.')
 process(a.cache,a.output,a.result_name)
