"""Fetch exact recorded evidence sources; hash-check every download.

Large raw files are intentionally outside the portable result bundle. Choose an
explicit cache directory. NASA groups use the OS credential; no credential enters
the manifest or public-data requests.
"""
from pathlib import Path
from urllib.parse import urlsplit
import argparse,json
from validate_evidence import digest
import earthdata_access
BASE=Path(__file__).resolve().parent;V=BASE/'data/validation'

def main(group,out):
 import requests
 if group=='archives':sources=json.loads((V/'download-manifest.json').read_text())
 elif group=='noaa':sources=json.loads((V/'coverage-sources.json').read_text())
 else:
  name='aqua-coverage-v3.json' if group=='aqua' else 'nasa-viirs-coverage.json'
  sources=[s for g in json.loads((V/name).read_text())['granules'] for s in g['sources']]
 out.mkdir(parents=True,exist_ok=True);token=earthdata_access.read_token() if group in ('aqua','nasa-viirs') else None
 if group in ('aqua','nasa-viirs') and not token:raise RuntimeError('Run Configure-Earthdata.cmd locally first.')
 for s in sources:
  name=s.get('file',s.get('id'));assert name==Path(name).name;path=out/name
  if not path.exists():
   if token:earthdata_access.download(s['url'],path,token)
   else:
    u=urlsplit(s['url'])
    if u.scheme!='https' or u.hostname not in ('firms.modaps.eosdis.nasa.gov','noaa-nesdis-n20-pds.s3.amazonaws.com'):raise RuntimeError('Unexpected public source host')
    part=path.with_suffix(path.suffix+'.part')
    try:
     with requests.get(s['url'],stream=True,timeout=(20,90)) as r:
      r.raise_for_status();n=0
      with part.open('wb') as f:
       for b in r.iter_content(262144):
        n+=len(b)
        if n>350*1024**2:raise RuntimeError('Source size limit exceeded')
        f.write(b)
     if digest(part)!=s['sha256']:raise RuntimeError('Downloaded content differs from the recorded evidence')
     part.replace(path)
    finally:
     if part.exists():part.unlink()
  if digest(path)!=s['sha256']:raise RuntimeError('Cached source SHA-256 mismatch: '+name)
  print('Verified',name,flush=True)
 if token:(out/'manifest.json').write_text(json.dumps(sources,indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('group',choices=['archives','noaa','aqua','nasa-viirs']);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 try:main(a.group,a.output)
 except Exception as e:print('Source fetch failed:',type(e).__name__);raise SystemExit(1)
