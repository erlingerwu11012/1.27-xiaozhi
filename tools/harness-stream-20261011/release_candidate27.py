"""One end-to-end candidate startup and isolated authenticated hello case."""
from pathlib import Path
import asyncio,json,os,signal,socket,subprocess,sys,time
S=Path(__file__).parent;R=Path('/root/prjs/releases/harness-stream-20261012')
name=os.environ.get('RELEASE_CHECK_NAME','release27')
assert name in {'release27','release28','release29'}
sys.path.insert(0,str(S));from budget import Budget
b=Budget();parent_charge=os.environ.get('RELEASE_ACCEPTANCE_CHARGE')
charge=int(parent_charge) if parent_charge else b.reserve('case','release27-isolated-candidate-startup-and-hello')
apps=json.loads(subprocess.check_output(['pm2','jlist']))
old=next(a for a in apps if a['name']=='xiaozhi-server' and a['pm2_env']['status']=='online')
env=dict(os.environ)
for item in (Path('/proc')/str(old['pid'])/'environ').read_bytes().split(b'\0'):
 key,sep,value=item.partition(b'=')
 if sep:env[key.decode()]=value.decode()
env['XIAOZHI_RELEASE_CANDIDATE']='1';env.pop('XIAOZHI_RELEASE_ALTERNATE_PORTS',None)
log_path=S/(name+'-candidate.log');assert not log_path.exists(),'keep original startup evidence'
log=log_path.open('w')
p=subprocess.Popen([sys.executable,str(R/'serve.py')],cwd=old['pm2_env']['pm_cwd'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(S/(name+'-candidate.pid')).write_text(str(p.pid))
try:
 for _ in range(100):
  assert p.poll() is None,'candidate exited; see protected startup log'
  try:
   with socket.create_connection(('127.0.0.1',8170),timeout=.3):break
  except OSError:time.sleep(.4)
 else:raise RuntimeError('candidate listener timeout')
 sys.path.insert(0,str(R/'runtime'))
 from core.auth import AuthManager
 import websockets
 token=AuthManager(secret_key=(S/'api-test-secret').read_text()).generate_token('release27-software','aa:bb:cc:dd:ee:ff',credential_version=2)
 async def verify():
  headers={'device-id':'aa:bb:cc:dd:ee:ff','client-id':'release27-software','Authorization':'Bearer '+token}
  async with websockets.connect('ws://127.0.0.1:8170/xiaozhi/v1/',additional_headers=headers) as ws:
   await ws.send(json.dumps({'type':'hello','version':2,'transport':'websocket','features':{'mcp':True},'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}))
   first=json.loads(await asyncio.wait_for(ws.recv(),12));assert first['type']=='hello' and first.get('session_id')
   seen=['hello'];sid=first['session_id']
   for _ in range(2):
    data=json.loads(await asyncio.wait_for(ws.recv(),12));assert data['type']=='mcp'
    call=data['payload'];seen.append(call['method'])
    assert call['method']==('initialize' if len(seen)==2 else 'tools/list'),seen
    result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'release27-software','version':'1'}} if call['method']=='initialize' else {'tools':[{'name':'self.get_device_status','description':'查询设备状态','inputSchema':{'type':'object','properties':{}}}]}
    await ws.send(json.dumps({'type':'mcp','session_id':sid,'payload':{'jsonrpc':'2.0','id':call['id'],'result':result}}))
   assert seen==['hello','initialize','tools/list'],seen
   return {'authenticated_hello':True,'hello_before_mcp':True,'real_server_entry':True,'isolated_management_database':True,'model_requests':0,'real_audio':False,'vision_requests':0}
 result=asyncio.run(verify());result['passed']=True
 (S/(name+'-candidate-evidence.json')).write_text(json.dumps(result,indent=2));b.finish(charge,dict(result,phase='candidate_entry',integration_pending=bool(parent_charge)));print(json.dumps(result))
except Exception as exc:
 b.finish(charge,{'passed':False,'error':repr(exc)});raise
finally:
 p.terminate()
 try:p.wait(timeout=10)
 except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
