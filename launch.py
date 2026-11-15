"""Start BurnWindow locally, then open the browser. Does not change system settings."""
from pathlib import Path
import sys,subprocess,time,urllib.request,json,webbrowser
from engine import VERSION
ROOT=Path(__file__).resolve().parent;URL='http://127.0.0.1:8766'
def ready():
 try:
  with urllib.request.urlopen(URL+'/api/health',timeout=1) as r:return json.load(r).get('engine')==VERSION
 except Exception:return False
if not ready():
 options={'cwd':str(ROOT),'stdout':(ROOT/'server.log').open('a',encoding='utf-8'),'stderr':subprocess.STDOUT}
 if sys.platform=='win32':options['creationflags']=subprocess.CREATE_NO_WINDOW
 subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port','8766'],**options)
 for _ in range(60):
  if ready():break
  time.sleep(.25)
 else:raise SystemExit('The server could not start. See server.log; run python server.py --port 8766 for diagnostics.')
webbrowser.open(URL)
print('BurnWindow is running at '+URL)
