"""User-run Earthdata setup. Tokens never enter files, URLs, logs or CLI arguments.

Windows storage is an OS-managed Generic Credential scoped to the current user.
The local application reports only configured/not-configured; it cannot return
the secret. Downloads send the bearer token only to fixed NASA data hosts and
never follow authenticated redirects to arbitrary hosts.
"""
from pathlib import Path
import os,sys,ctypes,getpass,json,argparse,hashlib
from ctypes import wintypes
from urllib.parse import urlsplit,urljoin
TARGET='BurnWindow/NASA-Earthdata'
ALLOWED={'data.lpdaac.earthdatacloud.nasa.gov','data.laadsdaac.earthdatacloud.nasa.gov','ladsweb.modaps.eosdis.nasa.gov'}
# Observed HTTPS redirect distributions issued by the two official NASA hosts.
# Bearer credentials are never sent to these content-delivery hosts.
NASA_CDN={'d1nklfio7vscoe.cloudfront.net','d13j1jds5ybppo.cloudfront.net'}
BASE=Path(__file__).resolve().parent

class Credential(ctypes.Structure):
 _fields_=[('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]

def vault():
 if sys.platform!='win32':raise RuntimeError('Use the EARTHDATA_TOKEN process environment on non-Windows systems.')
 lib=ctypes.WinDLL('advapi32',use_last_error=True)
 lib.CredWriteW.argtypes=[ctypes.POINTER(Credential),wintypes.DWORD];lib.CredWriteW.restype=wintypes.BOOL
 lib.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))];lib.CredReadW.restype=wintypes.BOOL
 lib.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD];lib.CredDeleteW.restype=wintypes.BOOL
 lib.CredFree.argtypes=[ctypes.c_void_p]
 return lib

def read_token():
 if os.environ.get('EARTHDATA_TOKEN'):return os.environ['EARTHDATA_TOKEN']
 if sys.platform!='win32':return None
 lib=vault();p=ctypes.POINTER(Credential)()
 if not lib.CredReadW(TARGET,1,0,ctypes.byref(p)):
  if ctypes.get_last_error()==1168:return None
  raise RuntimeError('Windows Credential Manager could not be read.')
 try:return ctypes.string_at(p.contents.CredentialBlob,p.contents.CredentialBlobSize).decode('utf-8')
 finally:lib.CredFree(p)

def configured():
 try:return bool(read_token())
 except RuntimeError:return False

def store_token(value):
 if not value or len(value)>2500 or any(c.isspace() for c in value):raise ValueError('Enter one Earthdata token without whitespace.')
 encoded=value.encode();blob=(ctypes.c_ubyte*len(encoded)).from_buffer_copy(encoded)
 c=Credential();c.Type=1;c.TargetName=TARGET;c.Comment='NASA Earthdata bearer token for local BurnWindow downloads';c.CredentialBlobSize=len(encoded);c.CredentialBlob=ctypes.cast(blob,ctypes.POINTER(ctypes.c_ubyte));c.Persist=2;c.UserName='Earthdata bearer token'
 if not vault().CredWriteW(ctypes.byref(c),0):raise RuntimeError('Windows Credential Manager did not save the token.')

def authorized_url(url):
 u=urlsplit(url)
 return u.scheme=='https' and u.hostname in ALLOWED and not u.username and not u.password and not u.query and not u.fragment

def data_response(url,token):
 import requests
 current=url
 for _ in range(4):
  u=urlsplit(current);is_nasa=u.hostname in ALLOWED
  is_s3=bool(u.hostname and '.s3' in u.hostname and u.hostname.endswith('.amazonaws.com'))
  if u.scheme!='https' or u.username or u.password or not(is_nasa or is_s3 or u.hostname in NASA_CDN):raise RuntimeError('NASA redirected to sign-in or an unsupported host. Authorize the data application in Earthdata and retry.')
  # A NASA-issued temporary S3 link is used without the Earthdata bearer header.
  r=requests.get(current,headers={'Authorization':'Bearer '+token} if is_nasa else {},stream=True,allow_redirects=False,timeout=(20,90))
  if r.status_code not in (301,302,303,307,308):return r
  nxt=urljoin(current,r.headers.get('Location',''));r.close();current=nxt
 raise RuntimeError('Too many NASA data redirects; nothing was imported.')

def download(url,path,token):
 import requests
 if not authorized_url(url):raise ValueError('Download host is not in the NASA allowlist')
 part=path.with_suffix(path.suffix+'.part')
 try:
  with data_response(url,token) as r:
   if r.status_code in (301,302,303,307,308):raise RuntimeError('NASA returned a sign-in/redirect response. Check token permissions or accept the data application in Earthdata; no credentials were forwarded.')
   if r.status_code!=200:raise RuntimeError(f'NASA download returned HTTP {r.status_code}; verify the token and data application authorization.')
   size=0;magic=b''
   with part.open('wb') as f:
    for b in r.iter_content(262144):
     if not magic:magic=b[:8]
     size+=len(b)
     if size>300*1024**2:raise RuntimeError('NASA source exceeded the 300 MB per-file cap')
     f.write(b)
  if magic[:4]!=b'\x0e\x03\x13\x01' and magic[:8]!=b'\x89HDF\r\n\x1a\n':raise RuntimeError('NASA returned content without a recognized HDF signature; it was not imported.')
  part.replace(path)
 finally:
  if part.exists():part.unlink()

def fetch_aqua(cache,check_only=False):
 token=read_token()
 if not token:raise RuntimeError('Earthdata is not configured. Run Configure-Earthdata.cmd locally.')
 plan=json.loads((BASE/'data/validation/aqua-download-plan.json').read_text());cache.mkdir(parents=True,exist_ok=True);manifest=[]
 for item in plan['sources'][:1] if check_only else plan['sources']:
  path=cache/item['file']
  if check_only or not path.exists():download(item['url'],path,token)
  digest=hashlib.sha256(path.read_bytes()).hexdigest();manifest.append({**item,'sha256':digest,'bytes':path.stat().st_size});print('Verified NASA HDF download:',path.name,flush=True)
 if not check_only:(cache/'manifest.json').write_text(json.dumps(manifest,indent=2))
 print('Earthdata download access confirmed.' if check_only else 'Aqua mask/geolocation sources downloaded. Run the native Aqua QA decoder next.')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['configure','status','check','download','forget']);p.add_argument('--cache',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(BASE)))/'BurnWindow'/'earthdata-cache');a=p.parse_args()
 try:
  if a.action=='status':print('Configured' if configured() else 'Not configured')
  elif a.action=='forget':
   if not vault().CredDeleteW(TARGET,1,0) and ctypes.get_last_error()!=1168:raise RuntimeError('Could not remove the saved credential.')
   print('BurnWindow Earthdata credential removed from Windows Credential Manager.')
  elif a.action=='configure':
   print('Create a token at https://urs.earthdata.nasa.gov/ using NASA instructions. Input below is hidden; never paste it into chat.')
   if not sys.stdin.isatty():raise RuntimeError('Run this command in your own interactive terminal so token input can be hidden.')
   value=getpass.getpass('Earthdata token (hidden): ').strip();store_token(value);del value
   print('Saved in Windows Credential Manager as '+TARGET+'. No token was written to the application folder.');fetch_aqua(a.cache,check_only=True)
  else:fetch_aqua(a.cache,check_only=a.action=='check')
 except (ValueError,RuntimeError) as e:print(str(e));sys.exit(1)
 except Exception as e:print('Access check failed ('+type(e).__name__+'). No credential details are logged.');sys.exit(1)
