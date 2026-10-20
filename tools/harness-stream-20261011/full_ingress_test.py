"""Real WebSocketServer/ConnectionHandler entry and isolated management auth.

External ASR/TTS/model component initialization is disabled; no model or hardware
calls. Hello, token verification, management HTTP, MCP and listen routing are real.
"""
import bootstrap,asyncio,json,copy,time
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import pymysql,websockets
from bootstrap import stage,budget
from config.manage_api_client import ManageApiClient
from core.websocket_server import WebSocketServer
from core.connection import ConnectionHandler

async def main():
 e=json.loads((stage/'private-test-env.json').read_text());assert e['PERSON_MEMORY_TEST_DATABASE'].startswith('bailian_memory_test_')
 db=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
 with db.cursor() as q:
  q.execute("INSERT IGNORE INTO ai_device(id,user_id,mac_address,agent_id) VALUES('device_ws_isolated',99003,'aa:bb:cc:dd:ee:ff','agent_http')")
  q.execute("INSERT INTO ai_device_ws_auth(device_id,credential_version,status) VALUES('aabbccddeeff',1,'active') ON DUPLICATE KEY UPDATE credential_version=1,status='active'")
 cfg=json.loads(Path('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json').read_text())
 cfg['read_config_from_api']=False;cfg['manager-api']={'url':'http://127.0.0.1:18002/xiaozhi','secret':(stage/'api-test-secret').read_text(),'max_retries':0}
 cfg['server']=dict(cfg['server'],ip='127.0.0.1',port=8180,auth_key=(stage/'api-test-secret').read_text(),auth={'enabled':True,'allowed_devices':[]})
 ManageApiClient(cfg);evidence=[]
 def components(c):c.vad=SimpleNamespace();c.asr=SimpleNamespace();c._pipeline_v2_frozen=True
 async def record(label,fn):
  charge=budget.reserve('case','full-entry:'+label)
  try:r=await fn();evidence.append({'case':label,'passed':True,'result':r});budget.finish(charge,{'passed':True})
  except Exception as exc:evidence.append({'case':label,'passed':False,'error':repr(exc)});budget.finish(charge,{'passed':False});raise
 with patch('core.websocket_server.initialize_modules',return_value={}),patch.object(ConnectionHandler,'_initialize_private_config',lambda c:None),patch.object(ConnectionHandler,'_initialize_components',components):
  host=WebSocketServer(cfg);server=await websockets.serve(host._handle_connection,'127.0.0.1',8180)
  token=host.auth.generate_token('software-device','aa:bb:cc:dd:ee:ff')
  headers={'device-id':'aa:bb:cc:dd:ee:ff','client-id':'software-device','Authorization':'Bearer '+token}
  async def connect(h=None):return await websockets.connect('ws://127.0.0.1:8180/xiaozhi/v1/',additional_headers=h or headers)
  async def rejected(message=None,h=None):
   ws=await connect(h)
   try:
    if message is not None:await ws.send(json.dumps(message))
    messages=[]
    try:
     while True:messages.append(json.loads(await asyncio.wait_for(ws.recv(),5)))
    except websockets.exceptions.ConnectionClosed:pass
    assert ws.close_code in {1002,1008},(ws.close_code,messages)
    return {'close_code':ws.close_code,'types':[x.get('type') for x in messages]}
   finally:await ws.close()
  async def hello(version):
   ws=await connect();await ws.send(json.dumps({'type':'hello','version':version,'transport':'websocket','features':{'mcp':True},'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}))
   seen=[];sid=None
   while len(seen)<3:
    msg=json.loads(await asyncio.wait_for(ws.recv(),5));seen.append(msg.get('type'))
    if msg.get('type')=='hello':sid=msg['session_id']
    if msg.get('type')=='mcp':
     p=msg['payload'];result={'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'software-device','version':'1'}} if p['method']=='initialize' else {'tools':[{'name':'self.get_device_status','description':'查询设备音量和屏幕亮度','inputSchema':{'type':'object','properties':{}}}]}
     await ws.send(json.dumps({'type':'mcp','session_id':sid,'payload':{'jsonrpc':'2.0','id':p['id'],'result':result}}))
   for _ in range(100):
    handler=(host._connections.get(headers['device-id']) or {}).get(sid)
    if handler and handler.mcp_client and handler.mcp_client.tools:break
    await asyncio.sleep(.01)
   assert handler and handler.protocol_version==version and handler.mcp_client.tools
   return ws,handler,{'version':version,'hello_before_initialize':seen[0]=='hello','tools':list(handler.mcp_client.tools)}
  try:
   await record('invalid-token',lambda:rejected(h=dict(headers,Authorization='Bearer invalid')))
   await record('hello-required',lambda:rejected({'type':'listen','state':'start','mode':'auto'}))
   await record('invalid-hello-version',lambda:rejected({'type':'hello','version':999}))
   for version in (1,2):
    async def version_case():
     ws,h,r=await hello(version)
     try:
      assert r['hello_before_initialize'];await ws.send(json.dumps({'type':'listen','state':'start','mode':'auto','session_id':h.session_id,'generation':1}))
      for _ in range(50):
       if h.device_listening:break
       await asyncio.sleep(.01)
      assert h.device_listening;epoch=h.listen_epoch
      await ws.send(json.dumps({'type':'listen','state':'start','mode':'auto','session_id':h.session_id,'generation':1}));await asyncio.sleep(.05)
      assert h.listen_epoch==epoch
      return dict(r,listen_generation_stable=True)
     finally:await ws.close()
    await record('old-firmware-protocol-'+str(version),version_case)
   async def stale():
    ws,h,r=await hello(2)
    try:
     await ws.send(json.dumps({'type':'listen','state':'start','session_id':'obsolete'}));await ws.wait_closed();assert ws.close_code==1008
     return {'stale_session_rejected':True}
    finally:await ws.close()
   await record('stale-session',stale)
   async def reconnect():
    first,old,_=await hello(2);second,new,_=await hello(2)
    try:
     assert old.session_id!=new.session_id and old.superseded and host.is_current_connection(headers['device-id'],new)
     assert not await host.send_json_to_device(headers['device-id'],{'type':'test'},session_id=old.session_id)
     return {'old_generation_cannot_send':True}
    finally:await first.close();await second.close()
   await record('reconnection-generation',reconnect)
   with db.cursor() as q:q.execute("UPDATE ai_device_ws_auth SET credential_version=2 WHERE device_id='aabbccddeeff'")
   await record('revoked-token',lambda:rejected())
  finally:
   server.close();await server.wait_closed();db.close()
   (stage/'full-ingress-evidence.json').write_text(json.dumps({'evidence_type':'real_loopback_server_real_isolated_management_software_components','cases':evidence,'production_modified':False},ensure_ascii=False,indent=2))
 print('FULL_INGRESS',len(evidence),'passed',flush=True)
asyncio.run(main())
