"""Download the pinned public science snapshot; preserve existing local files."""
from pathlib import Path
import hashlib,json,urllib.request,zipfile,tempfile,shutil

ROOT=Path(__file__).resolve().parent
def main():
 manifest=json.loads((ROOT/'data-bundle.json').read_text())
 if all((ROOT/name).exists() for name in manifest['files']):
  print('Data files already present; local data preserved.');return
 with tempfile.TemporaryDirectory(prefix='burnwindow-') as tmp:
  archive=Path(tmp)/'data.zip';h=hashlib.sha256();size=0
  with urllib.request.urlopen(manifest['url'],timeout=120) as response,archive.open('wb') as out:
   while chunk:=response.read(1048576):
    size+=len(chunk)
    if size>manifest['bytes']:raise ValueError('Download exceeded recorded size.')
    h.update(chunk);out.write(chunk)
  if size!=manifest['bytes'] or h.hexdigest()!=manifest['sha256']:raise ValueError('Data archive checksum mismatch.')
  with zipfile.ZipFile(archive) as z:
   if set(z.namelist())!=set(manifest['files']):raise ValueError('Unexpected archive members.')
   for name,want in manifest['files'].items():
    target=(ROOT/name).resolve()
    if not target.is_relative_to((ROOT/'data').resolve()):raise ValueError('Unsafe archive path.')
    if target.exists():continue
    target.parent.mkdir(parents=True,exist_ok=True);part=target.with_suffix(target.suffix+'.part');h=hashlib.sha256()
    try:
     with z.open(name) as source,part.open('wb') as out:
      while chunk:=source.read(1048576):h.update(chunk);out.write(chunk)
     if h.hexdigest()!=want:raise ValueError('Data member checksum mismatch.')
     part.replace(target)
    finally:
     if part.exists():part.unlink()
 print('Verified public data snapshot ready.')
if __name__=='__main__':main()
