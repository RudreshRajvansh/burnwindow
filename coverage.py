"""Native NOAA EFIRE v1r3 QA + exact named GITCO geolocation evidence.

This validates decoded product labels and alignment, not the physical correctness
of the retrieval algorithm. Samples are pixel visits, never area coverage. NASA
Aqua or VIIRS standard-product coverage is not inferred from this NOAA product.
"""
from pathlib import Path
import json,hashlib,sys,argparse,re
from datetime import datetime,timezone

CLASS_NAMES=['not_processed','bowtie_deleted','sun_glint','water','cloud','clear_nonfire_land','unclassified','low_confidence_fire','nominal_fire','high_confidence_fire','qa_rejected','unknown_code']
REQUIRED_MASK_LEGEND=['0 not-processed','1 bowtie','2 glint','3 water','4 clouds','5 clear land','6 unclassified','7 low confidence fire','8 nominal confidence fire','9 high confidence fire']
REQUIRED_QA_LEGEND=['0: Band1_isBad','1: Band2_isBad','2: Band3_isBad','3: Band4_isBad','4: Band5_isBad','5: Geo_isBad','6: Band13_isBad','22: Bowtie']

def decoded(x):return x.decode() if isinstance(x,bytes) else str(x)

def validate_legends(mask_legend,qa_legend):
 if not all(s in mask_legend for s in REQUIRED_MASK_LEGEND):raise ValueError('Unknown fire-mask schema; refusing inferred classes')
 if not all(s in qa_legend for s in REQUIRED_QA_LEGEND):raise ValueError('Unknown QA schema; refusing inferred bit meanings')

def classified(mask,qa):
 import numpy as np
 if mask.shape!=qa.shape:raise ValueError('Mask/QA shape mismatch')
 out=np.where(mask<=9,mask,11).astype('uint8')
 # Preserve observed cloud/water/deleted/unclassified categories; reject a claim
 # of clear land or accepted fire if any input QA or bowtie bit is non-nominal.
 bad=((qa & 127)!=0)|((qa & (1<<22))!=0)
 out[bad&np.isin(mask,[5,7,8,9])]=10
 return out

def check_pair(fire_name,geo_name,source,platform,geo_platform,mask_shape,geo_shape):
 if geo_name not in source.split(','):raise ValueError('Geolocation is not the exact input named by the fire product')
 if platform!='n20' or geo_platform!='J01':raise ValueError('Platform mismatch')
 if mask_shape!=geo_shape or len(mask_shape)!=2:raise ValueError('Full raster/geolocation shape mismatch')
 start=re.search(r'_s(\d{15})_',fire_name);gt=re.search(r'_d(\d{8})_t(\d{7})_',geo_name)
 if not start or not gt or start.group(1)!=gt.group(1)+gt.group(2):raise ValueError('Acquisition timestamp mismatch')

def process(cache,output):
 import numpy as np,h5py
 from validate_evidence import digest
 selection=json.loads((output/'coverage-selection.json').read_text());sources=json.loads((output/'coverage-sources.json').read_text());byfile={s['file']:s for s in sources}
 assert digest(output/'coverage-amendment.json')==selection['amendment_sha256']
 box=[-124,42,-116,46];granules=[];totals=np.zeros(len(CLASS_NAMES),dtype='int64');map_bins={};cropdir=output/'pixel-evidence';cropdir.mkdir(exist_ok=True)
 for candidate in selection['candidates']:
  fn=Path(candidate['key']).name;gn=Path(candidate['geolocation']['key']).name;record={'fire_file':fn,'geolocation_file':gn,'sources':[byfile[fn],byfile[gn]],'status':'verified_product_samples'}
  try:
   assert digest(cache/fn)==byfile[fn]['sha256'];assert digest(cache/gn)==byfile[gn]['sha256']
   with h5py.File(cache/fn) as f,h5py.File(cache/gn) as g:
    latds=g['All_Data/VIIRS-IMG-GEO-TC_All/Latitude'];londs=g['All_Data/VIIRS-IMG-GEO-TC_All/Longitude'];maskds=f['fire_mask'];qads=f['fire_qa']
    check_pair(fn,gn,decoded(f.attrs['source']),decoded(f.attrs['platform']),decoded(g.attrs['Platform_Short_Name'][0,0]),maskds.shape,latds.shape)
    if maskds.shape!=qads.shape or latds.shape!=londs.shape:raise ValueError('Array dimensions differ')
    ml=decoded(maskds.attrs['Legend']);ql=decoded(qads.attrs['Legend']);validate_legends(ml,ql)
    record.update(mask_legend=ml,qa_legend=ql,algorithm=decoded(f.attrs['history']),daynight=decoded(f.attrs['day_night_data_flag']),start=decoded(f.attrs['time_coverage_start']),end=decoded(f.attrs['time_coverage_end']),native_shape=list(maskds.shape))
    # Process by scan blocks so full-resolution geolocation stays memory-bounded.
    counts=np.zeros(len(CLASS_NAMES),dtype='int64');bad_coordinates=0;crop={k:[] for k in ['row','col','latitude','longitude','fire_mask','fire_qa']}
    for first in range(0,maskds.shape[0],128):
     lat=latds[first:first+128];lon=londs[first:first+128];valid=np.isfinite(lat)&np.isfinite(lon)&(abs(lat)<=90)&(abs(lon)<=180);bad_coordinates+=int(np.sum(~valid))
     sel=valid&(lon>=box[0])&(lon<=box[2])&(lat>=box[1])&(lat<=box[3])
     if not np.any(sel):continue
     rr,cc=np.where(sel);ma=maskds[first:first+128][sel];qa=qads[first:first+128][sel];classes=classified(ma,qa);counts+=np.bincount(classes,minlength=len(CLASS_NAMES))
     for k,val in [('row',(rr+first).astype('uint16')),('col',cc.astype('uint16')),('latitude',lat[sel]),('longitude',lon[sel]),('fire_mask',ma),('fire_qa',qa)]:crop[k].append(val)
     # Display bins only; percentages use native sample counts, not square km.
     gx=np.floor((lon[sel]+124)*10).astype(int);gy=np.floor((lat[sel]-42)*10).astype(int)
     for key in np.unique(gx*100+gy):
      at=(gx*100+gy)==key;cell=map_bins.setdefault(int(key),np.zeros(len(CLASS_NAMES),dtype='int64'));cell+=np.bincount(classes[at],minlength=len(CLASS_NAMES))
    # Verify full geolocation at sparse publisher fire pixels independently of AOI.
    line=f['FP_Line'][:].astype(int);column=f['FP_Sample'][:].astype(int);fp_lat=f['FP_Latitude'][:];fp_lon=f['FP_Longitude'][:]
    good=(line>=0)&(line<latds.shape[0])&(column>=0)&(column<latds.shape[1])&(abs(fp_lat)<=90)&(abs(fp_lon)<=180)
    diffs=[]
    for r,c,la,lo in zip(line[good],column[good],fp_lat[good],fp_lon[good]):
     la2=float(latds[r,c]);lo2=float(londs[r,c]);diffs.append(max(abs(float(la)-la2),abs(((float(lo)-lo2+180)%360)-180)))
    maxdiff=max(diffs,default=None)
    if maxdiff is not None and maxdiff>1e-4:raise ValueError('Sparse fire coordinates disagree with paired full geolocation')
    record.update(counts={k:int(n) for k,n in zip(CLASS_NAMES,counts)},pixel_samples=int(counts.sum()),unlocatable_samples_in_entire_granule=bad_coordinates,alignment_checks=len(diffs),max_alignment_error_degrees=maxdiff)
    if counts.sum():
     path=cropdir/(fn+'.npz');np.savez_compressed(path,**{k:np.concatenate(v) for k,v in crop.items()});record['pixel_evidence']={'file':'pixel-evidence/'+path.name,'sha256':digest(path),'bytes':path.stat().st_size}
    totals+=counts
  except Exception as exc:record.update(status='unverified',reason=str(exc))
  granules.append(record);print('QA',fn,record['status'],record.get('pixel_samples'),flush=True)
 # Map bins should only summarize verified swaths. Reject aggregate if any failed.
 complete=all(g['status']=='verified_product_samples' for g in granules)
 if not complete:map_bins={}
 result={'title':'Decoded cloud and swath QA pilot','date':'2024-08-15','bbox':box,'product':'NOAA-20 EFIRE-VIIRSI v1r3 + exact named GITCO input','selected_granules':len(granules),'verified_granules':sum(g['status']=='verified_product_samples' for g in granules),'selection_complete_for_sample':complete,'whole_day_complete':False,'global_coverage_verified':False,'aqua_coverage_verified':False,'nasa_standard_viirs_coverage_verified':False,'granules':granules,'counts':{k:int(v) for k,v in zip(CLASS_NAMES,totals)},'pixel_samples':int(totals.sum()),'display_bins':[{'lon':-124+(key//100+.5)/10,'lat':42+(key%100+.5)/10,'counts':{k:int(v) for k,v in zip(CLASS_NAMES,val)}} for key,val in map_bins.items()],'interpretation':'Decoded geolocated pixel visits for selected native swaths. Counts and cloud fractions are not area fractions, complete-day visibility, or NASA Aqua/VIIRS standard-product observation denominators. Unsampled space/time remains unknown. Classification is verified against file legends and alignment, not independently validated physical cloud truth.','sources':sources,'selection':selection,'processed_at_utc':datetime.now(timezone.utc).isoformat(),'processor_sha256':digest(__file__)}
 with (output/'coverage.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
 (output/'coverage.sha256').write_text(digest(output/'coverage.json')+'  coverage.json\n')
 print('COVERAGE SEALED',result['pixel_samples'],'native pixel visits',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--deps',type=Path);p.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'data/validation');a=p.parse_args()
 if a.deps:sys.path.insert(0,str(a.deps.resolve()))
 if (a.output/'coverage.json').exists():raise SystemExit('Coverage evidence already sealed; preserved without overwrite.')
 process(a.cache,a.output)
