"""Compare this device's existing credential on its server; never log secret material."""
from pathlib import Path
import json
import subprocess
import sys
from diagnose_ota import read_saved_settings

REMOTE = r'''
from pathlib import Path
import hashlib,hmac,json,os,socket,ssl,subprocess,urllib.parse,yaml
device_key=__DEVICE_KEY__
root=Path('/root/prjs/xiaozhi-esp32-server/main/manager-api/src/main/resources')
config=yaml.safe_load((root/'application-dev.yml').read_text())
db=config['spring']['datasource']['druid']
url=urllib.parse.urlsplit(db['url'].removeprefix('jdbc:'))
env=os.environ.copy()
env['MYSQL_PWD']=str(db['password'])
def sql(query):
    result=subprocess.run(['mysql','--protocol=TCP','-h',url.hostname,'-P',str(url.port or 3306),
        '-u',str(db['username']),'-N','-B','--raw',url.path.lstrip('/'),'-e',query],capture_output=True,text=True,env=env)
    if result.returncode: raise RuntimeError('Read-only DB query failed')
    return result.stdout.rstrip('\n')
secret=sql("SELECT param_value FROM sys_params WHERE param_code='server.secret' LIMIT 1")
row=sql("SELECT status,credential_version,bootstrap_key_hash FROM ai_device_ws_auth WHERE device_id='aca704fd205c'").split('\t')
out={'device_status':row[0], 'credential_version':int(row[1]),
     'saved_device_key_matches_server':hmac.compare_digest(hmac.new(secret.encode(),device_key.encode(),hashlib.sha256).hexdigest(),row[2])}
cfg=config['spring']['data']['redis']
sock=socket.create_connection((cfg.get('host','127.0.0.1'),int(cfg.get('port',6379))),timeout=5)
stream=sock.makefile('rb')
def command(*args):
    encoded=[str(x).encode() for x in args]
    sock.sendall(b'*'+str(len(encoded)).encode()+b'\r\n'+b''.join(b'$'+str(len(x)).encode()+b'\r\n'+x+b'\r\n' for x in encoded))
    line=stream.readline()
    kind,value=line[:1],line[1:-2]
    if kind==b'-': raise RuntimeError('Redis command rejected')
    if kind==b'$':
        n=int(value)
        if n<0:return None
        data=stream.read(n);stream.read(2);return data
    if kind==b':':return int(value)
    return value
if cfg.get('password'):command('AUTH',cfg['password'])
if cfg.get('database'):command('SELECT',cfg['database'])
name='ota:bootstrap:fail:aca704fd205c'
value=command('GET',name)
out['bootstrap_failure_count']=value.decode(errors='replace') if value is not None else None
out['bootstrap_failure_ttl_seconds']=command('TTL',name)
cached=command('HGET','sys:params','server.secret')
if cached is not None:
    cached=cached.decode()
    try: cached=json.loads(cached)
    except ValueError: pass
    if isinstance(cached,str):
        out['cached_secret_matches_database']=hmac.compare_digest(cached,secret)
        out['saved_device_key_matches_cached_server_secret']=hmac.compare_digest(hmac.new(cached.encode(),device_key.encode(),hashlib.sha256).hexdigest(),row[2])
sock.close()
print(json.dumps(out))
'''

def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    _, values = read_saved_settings()
    script = REMOTE.replace('__DEVICE_KEY__', json.dumps(values[('websocket', 'auth_key')]))
    result = subprocess.run(['C:/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','root@121.40.239.140','python3 -'],
                            input=script,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if result.returncode:
        # Do not echo the script or any input containing the device key.
        print(result.stderr)
        raise SystemExit(result.returncode)
    data=json.loads(result.stdout)
    (Path(__file__).parent/'evidence/server-credential-diagnostic.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps(data))

if __name__=='__main__':main()
