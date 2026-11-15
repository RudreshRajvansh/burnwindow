"""Optionally re-download pinned inputs and verify exact SHA-256. No source is executed."""
import argparse,hashlib,json,sys
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--source',required=True,help='Exact filename from data/download-manifest.json');p.add_argument('--output',default='data/verified');args=p.parse_args()
manifest=json.loads((ROOT/'data/download-manifest.json').read_text());item=manifest.get(args.source)
if not item or 'sha256' not in item:raise SystemExit('Choose a source with a pinned SHA-256 in the download manifest.')
target=(ROOT/args.output).resolve()
if not target.is_relative_to(ROOT):raise SystemExit('Output must remain inside the application directory.')
target.mkdir(parents=True,exist_ok=True);part=target/(Path(args.source).name+'.part');digest=hashlib.sha256();size=0
try:
 with requests.get(item['url'],stream=True,timeout=(15,120)) as response:
  response.raise_for_status()
  with part.open('wb') as f:
   for block in response.iter_content(262144):
    size+=len(block)
    if size>350*1024**2:raise ValueError('Source exceeds size limit')
    digest.update(block);f.write(block)
 if digest.hexdigest()!=item['sha256']:raise ValueError('Source changed since capture; SHA-256 differs. Rolling files normally change. Cached analysis is retained.')
 part.replace(target/Path(args.source).name);print('Verified',args.source,digest.hexdigest())
finally:
 if part.exists():part.unlink()
