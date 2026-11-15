"""NASA VJ114IMG Collection 2 native masks with their exact VJ103IMG input.

QA bits 0–6 (input quality) and 22 (residual bowtie) use the NASA Collection 2
user-guide contract, independently of NOAA's operational product. Counts remain
pixel visits; they are not deduplicated area or verified physical cloud truth.
"""
from pathlib import Path
import json,argparse,sys
from datetime import datetime,timezone
from validate_evidence import digest
from coverage import CLASS_NAMES,classified,decoded

GUIDE='https://ladsweb.modaps.eosdis.nasa.gov/archive/Document%20Archive/Science%20Data%20Product%20Documentation/VIIRS_C2_AF-375m_User_Guide_1.2.pdf'

def process(cache,output):
 import numpy as np,h5py
 plan=json.loads((output/'nasa-viirs-download-plan.json').read_text());manifest={r['file']:r for r in json.loads((cache/'manifest.json').read_text())};records=[];total=np.zeros(len(CLASS_NAMES),dtype='int64');cropdir=output/'nasa-viirs-pixel-evidence';cropdir.mkdir(exist_ok=True)
 for pair in plan['pairs']:
  fn=pair['mask'];gn=pair['geolocation'];record={'mask_file':fn,'geolocation_file':gn,'state':'unverified'}
  try:
   for name in [fn,gn]:
    if digest(cache/name)!=manifest[name]['sha256']:raise ValueError('Native file hash mismatch')
   with h5py.File(cache/fn) as f,h5py.File(cache/gn) as g:
    if decoded(f.attrs['ShortName'])!='VJ114IMG' or decoded(f.attrs['VersionID'])!='002' or decoded(g.attrs['ShortName'])!='VJ103IMG' or decoded(g.attrs['VersionId'])!='021':raise ValueError('Unsupported NASA product/collection')
    if gn not in decoded(f.attrs['InputPointer']).split('/')[-1] and gn not in decoded(f.attrs['InputPointer']):raise ValueError('Geolocation is not the exact native input')
    if decoded(f.attrs['PlatformShortName'])!=decoded(g.attrs['platform']) or fn.split('.')[1:3]!=gn.split('.')[1:3]:raise ValueError('Platform/acquisition mismatch')
    ma=f['fire mask'];qa=f['algorithm QA'];lat=g['geolocation_data/latitude'];lon=g['geolocation_data/longitude']
    if len(ma.shape)!=2 or not ma.shape==qa.shape==lat.shape==lon.shape:raise ValueError('Native raster/geolocation dimensions differ')
    legend=decoded(ma.attrs['legend'][0])
    if not all(t in legend for t in ['0 not-processed','1 bowtie','2 glint','3 water','4 clouds','5 clear land','6 unclassified','7 low confidence','8 nominal confidence','9 high confidence']):raise ValueError('Unexpected NASA mask legend')
    rr=f['FP_line'][:].astype(int);cc=f['FP_sample'][:].astype(int);fl=f['FP_latitude'][:];fo=f['FP_longitude'][:];diff=[]
    good=(rr>=0)&(rr<ma.shape[0])&(cc>=0)&(cc<ma.shape[1])&(abs(fl)<=90)&(abs(fo)<=180)
    # Read sparse geolocation checks by raster rows, avoiding thousands of HDF chunk reads.
    for row in np.unique(rr[good]):
     at=good&(rr==row);la=lat[row,:][cc[at]];lo=lon[row,:][cc[at]];diff.extend(np.maximum(abs(la-fl[at]),abs((lo-fo[at]+180)%360-180)).tolist())
    if diff and max(diff)>1e-4:raise ValueError('Sparse fire coordinates disagree with full geolocation')
    counts=np.zeros(len(CLASS_NAMES),dtype='int64');crops={k:[] for k in ['row','col','latitude','longitude','fire_mask','algorithm_qa']};bad=0;w,s,e,n=plan['bbox']
    for first in range(0,ma.shape[0],128):
     la=lat[first:first+128];lo=lon[first:first+128];valid=np.isfinite(la)&np.isfinite(lo)&(abs(la)<=90)&(abs(lo)<=180);bad+=int(np.sum(~valid));sel=valid&(la>=s)&(la<=n)&(lo>=w)&(lo<=e)
     if not np.any(sel):continue
     m=ma[first:first+128][sel];q=qa[first:first+128][sel];counts+=np.bincount(classified(m,q),minlength=len(CLASS_NAMES));r,c=np.where(sel)
     for k,value in [('row',(r+first).astype('uint16')),('col',c.astype('uint16')),('latitude',la[sel]),('longitude',lo[sel]),('fire_mask',m),('algorithm_qa',q)]:crops[k].append(value)
    record.update(state='decoded_native_samples',product='VJ114IMG.002',start=decoded(f.attrs['StartTime']),end=decoded(f.attrs['EndTime']),daynight=decoded(f.attrs['DayNightFlag']),native_shape=list(ma.shape),counts=dict(zip(CLASS_NAMES,map(int,counts))),pixel_samples=int(counts.sum()),unlocatable_samples_in_entire_granule=bad,alignment_checks=len(diff),max_alignment_error_degrees=max(diff,default=None),mask_legend=legend,qa_contract_source=GUIDE,sources=[manifest[fn],manifest[gn]])
    if counts.sum():
     path=cropdir/(fn+'.npz');np.savez_compressed(path,**{k:np.concatenate(v) for k,v in crops.items()});record['pixel_evidence']={'file':'nasa-viirs-pixel-evidence/'+path.name,'sha256':digest(path),'bytes':path.stat().st_size}
    total+=counts
  except Exception as exc:record['reason']=str(exc)
  records.append(record);print('NASA VIIRS QA',fn,record['state'],record.get('pixel_samples'),flush=True)
 result={'product':'NASA NOAA-20 VJ114IMG.002 + exact VJ103IMG.021 input','date':plan['date'],'bbox':plan['bbox'],'granules':records,'counts':dict(zip(CLASS_NAMES,map(int,total))),'pixel_samples':int(total.sum()),'all_selected_decoded':all(r['state']=='decoded_native_samples' for r in records),'interpretation':'Native pixel observations in the selected box/day. Not pixel-area weighting or a global/history-wide observation denominator. Both day/night swaths remain separate and unobserved areas/times unknown. Product decoding and geolocation are checked; cloud-label physical accuracy is not independently established.','processor_sha256':digest(__file__),'processed_at_utc':datetime.now(timezone.utc).isoformat()}
 with (output/'nasa-viirs-coverage.json').open('x') as f:json.dump(result,f,indent=2)
 (output/'nasa-viirs-coverage.sha256').write_text(digest(output/'nasa-viirs-coverage.json')+'  nasa-viirs-coverage.json\n')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--deps',type=Path);p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'data/validation');a=p.parse_args()
 if a.deps:sys.path.insert(0,str(a.deps.resolve()))
 if (a.output/'nasa-viirs-coverage.json').exists():raise SystemExit('NASA VIIRS evidence exists; refusing overwrite.')
 process(a.cache,a.output)
