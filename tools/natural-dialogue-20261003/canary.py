"""Temporary single-device acceptance harness. Not part of production delivery.

The probe is a root-only Unix socket, never a public HTTP administrative API.
The normal WebSocket authentication and current-session send guard remain intact.
"""
import asyncio, json, os, sys, time
from pathlib import Path

ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
DEVICE='ac:a7:04:fd:20:2c'
SOCKET=OUT/'probe.sock'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
from config.settings import load_config
from core.websocket_server import WebSocketServer
from core.utils.operation_control import get_control, actor_scope
from core.utils.person_identity import activate, deactivate, freeze


async def main():
    config=load_config()
    config['server']['auth_key']=config['server'].get('auth_key') or config['manager-api']['secret']
    port=int(os.environ.get('NATURAL_DIALOGUE_PORT','8010'))
    assert port in {8010,8011}
    config['server']['ip']='127.0.0.1';config['server']['port']=port
    config['operation_control']={'enabled':True}
    config['close_connection_no_voice_time']=1800
    server=WebSocketServer(config)
    original=server._handle_connection
    async def only_device(ws):
        if (ws.request.headers.get('device-id')or'').lower()!=DEVICE:
            await ws.close(code=1008,reason='single test device only');return
        await original(ws)
    server._handle_connection=only_device
    async def probe(reader,writer):
        token=None
        try:
            data=json.loads(await asyncio.wait_for(reader.readline(),5))
            conn=server._current_connection(DEVICE)
            if not conn or not getattr(conn,'func_handler',None):
                response={'online':False}
            elif data['op']=='catalog':
                client=conn.mcp_client
                response={'online':True,'ready':client.ready,'catalog_version':client.catalog_version,
                    'tools':conn.func_handler.get_functions(),
                    'device_tools':client.get_available_tools(),
                    'persona_sha256':__import__('hashlib').sha256(str(conn.config.get('prompt','')).encode()).hexdigest(),
                    'identity_mode':(getattr(conn,'identity_state',{}) or {}).get('mode'),
                    'implementation_sha256':__import__('hashlib').sha256((ROOT/'core/utils/operation_control.py').read_bytes()).hexdigest()}
            elif data['op']=='call':
                allowed={'self_get_device_status','self_audio_speaker_set_volume','self_screen_set_brightness',
                    'self_camera_take_photo','add_reminder','note_add','note_list','note_delete','reminder_get_current'}
                if data['name'] not in allowed:raise ValueError('probe tool not allowed')
                # This is a server-owned test command, not a client speaker identity.
                actor=freeze(conn,{'mode':'unavailable'},status='system')
                token=activate(conn,actor)
                get_control(conn).begin(data.get('query') or '',actor_scope(conn))
                result=await asyncio.wait_for(conn.func_handler.tool_manager.execute_tool(data['name'],data.get('arguments',{})),65)
                response={'online':True,'action':result.action.name,'result':result.result,'response':result.response}
                if data['name']=='note_list':
                    # Keep customer note bodies out of diagnostic output.
                    raw=str(result.result or result.response or '')
                    import re,hashlib
                    lines=raw.splitlines()
                    response={'online':True,'test_entries':[line for line in lines if re.match(r'^\d+\. 自然对话验收-',line)],
                              'list_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                              'test_only_list':all(not line.strip() or re.match(r'^\d+\. 自然对话验收-',line) for line in lines)}
            elif data['op']=='chat':
                # Capture only this injected synthetic turn's new answer.
                text=str(data['text'])
                if len(text)>300:raise ValueError('test text too long')
                before=len(conn.dialogue.dialogue)
                actor=freeze(conn,{'mode':'unavailable'},status='system')
                ok=await asyncio.get_running_loop().run_in_executor(conn.executor,lambda:conn.chat(text,_identity=actor))
                answers=[m.caption_text or m.content for m in conn.dialogue.dialogue[before:] if m.role=='assistant' and not m.tool_calls]
                response={'online':True,'ok':ok,'answers':answers}
            else:raise ValueError('unknown operation')
        except Exception as exc:
            response={'error_type':type(exc).__name__}
        finally:
            if token is not None:deactivate(token)
        writer.write((json.dumps(response,ensure_ascii=False)+'\n').encode());await writer.drain()
        writer.close();await writer.wait_closed()
    if SOCKET.exists():SOCKET.unlink()
    unix=await asyncio.start_unix_server(probe,path=str(SOCKET));os.chmod(SOCKET,0o600)
    print('single-device canary ready',flush=True)
    async with unix:await server.start()

if __name__=='__main__':asyncio.run(main())
