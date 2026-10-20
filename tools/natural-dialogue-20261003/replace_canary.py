"""Prepare a healthy replacement before switching the one-device upstream."""
import json, os, socket, subprocess, time
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
rows=json.loads(subprocess.run(['pm2','jlist'],check=True,capture_output=True,text=True).stdout)
prod=next(p for p in rows if p['name']=='xiaozhi-server')
raw=Path('/proc/'+str(prod['pid'])+'/environ').read_bytes()
running={p.split(b'=',1)[0].decode():p.split(b'=',1)[1].decode() for p in raw.split(b'\0') if b'=' in p}
spec=json.loads((OUT/'private-canary.config.json').read_text())
app=spec['apps'][0];app['name']='natural-dialogue-canary-next'
names=['HW_BILLING_ENABLED','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN','HW_BILLING_SERVICE_KEY']
assert all(running.get(k) for k in names)
app['env'].update({k:running[k] for k in names})
app['env']['NATURAL_DIALOGUE_PORT']='8011'
app['out_file']=str(OUT/'canary-next-output.log');app['error_file']=str(OUT/'canary-next-error.log')
private=OUT/'private-canary-next.config.json';private.write_text(json.dumps(spec));os.chmod(private,0o600)
subprocess.run(['pm2','start',str(private)],check=True,capture_output=True)
for attempt in range(30):
    try:
        with socket.create_connection(('127.0.0.1',8011),timeout=1):pass
        break
    except OSError:
        if attempt==29:raise
        time.sleep(1)
config=Path('/etc/nginx/conf.d/natural-dialogue-canary.conf')
previous=config.read_text()
assert previous.count('server 127.0.0.1:8010;')==1
try:
    config.write_text(previous.replace('server 127.0.0.1:8010;','server 127.0.0.1:8011;'))
    subprocess.run(['nginx','-t'],check=True,capture_output=True)
    subprocess.run(['nginx','-s','reload'],check=True,capture_output=True)
except Exception:
    config.write_text(previous)
    subprocess.run(['nginx','-s','reload'],capture_output=True)
    raise
subprocess.run(['pm2','delete','natural-dialogue-canary'],check=True,capture_output=True)
print('replacement listening before route switch; internal billing environment matched; no credentials printed')
