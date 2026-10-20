import bootstrap,asyncio,types,time,json
from unittest.mock import MagicMock,AsyncMock
from bootstrap import budget,stage
from core.websocket_server import WebSocketServer
from test_support import connection
from stateful_device import StatefulDevice
async def main():
 results=[]
 for mode in ['ok','timeout','stale']:
  budget.reserve('case','ws-send:'+mode);s=WebSocketServer.__new__(WebSocketServer);s.logger=MagicMock();s.config={'server':{'ws_send_timeout_seconds':.05}};lock=asyncio.Lock();s._get_device_send_lock=lambda _:lock;s.is_current_connection=lambda *a:mode!='stale'
  async def send(_):
   if mode=='timeout':await asyncio.sleep(.2)
  mock=AsyncMock(side_effect=send);c=types.SimpleNamespace(websocket=types.SimpleNamespace(send=mock),session_id='s');ok=await s.send_to_current('d','test',handler=c);assert ok==(mode=='ok');assert mock.await_count==(0 if mode=='stale' else 1);results.append({'mode':mode,'ok':ok})
 for key,query in [('volume','大声一点'),('level','亮一点')]:
  budget.reserve('case','boundary-no-repeat:'+key);m=StatefulDevice();m.state[key]=100 if key=='volume' else 5;m.save();c,m,h=connection(m);out=await h.run(query,[]);assert '已到可调边界' in out.reply,out.reply;assert len(m.calls)==1,m.calls;results.append({'query':query,'speech':out.reply})
 (stage/'ws-boundary-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print('WS/boundary PASS',len(results),budget.report())
asyncio.run(main())
