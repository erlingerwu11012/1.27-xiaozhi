import bootstrap,asyncio,json,types,re,time
from unittest.mock import patch
from bootstrap import stage,budget
from core.utils.vision_readiness import ensure_vision
from core.utils.tool_harness.runtime import live_read_request
from core.utils.tool_harness.memory_policy import memory_intent,normalize_fact
from core.utils.tool_harness.models import StepResult
from core.utils.tool_harness.reply_composer import unsafe,status_conflict
from core.providers.tools.device_mcp.mcp_client import MCPClient
from aiohttp import web
rows=[]
def check(name,fn):
 budget.reserve('case','supplement:'+name)
 try:fn();rows.append({'name':name,'passed':True})
 except Exception as e:rows.append({'name':name,'passed':False,'error':str(e)})
def equal(a,b):assert a==b,(a,b)
async def vision(name,states,expected,mutate=False):
 budget.reserve('case','supplement:'+name);calls=[]
 c=types.SimpleNamespace(mcp_client=MCPClient(),session_id='session-new',device_id='synthetic',config={})
 c.mcp_client.capabilities={'experimental':{'visionStatus':1}}
 async def send(conn,msg):
  calls.append(msg['method']);state=dict(states[min(len(calls)-1,len(states)-1)])
  if mutate:conn.session_id='session-replaced'
  state.setdefault('session_id','session-new');conn.mcp_client.call_results[msg['id']].set_result(state)
 try:
  with patch('core.providers.tools.device_mcp.mcp_handler.send_mcp_message',send),patch('core.utils.vision_capability.build_vision_capabilities',return_value=types.SimpleNamespace(ok=True,vision={'token':'synthetic'})),patch('core.utils.account_identity.resolve_face_account_id',return_value='synthetic'):
   try:r=await ensure_vision(c)
   except ValueError as e:r=str(e)
   equal(calls,expected);assert not c.mcp_client.call_results
   if mutate or states[0].get('session_id')=='old':equal(r,'vision_session_mismatch')
   if len(expected)>1:assert r['explain_ready']
   if expected==['vision/status','vision/refresh']:
    c._vision_refresh_at=time.monotonic();states[:]=[{'explain_ready':False,'explain_reason':'awaiting_initialize'}];calls.clear();await ensure_vision(c);equal(calls,['vision/status'])
  rows.append({'name':name,'passed':True})
 except Exception as e:rows.append({'name':name,'passed':False,'error':repr(e)})
async def main():
 for q,expected in [('这是最高档了吗','self_get_device_status'),('屏幕亮度现在多少','self_get_device_status'),('现在屏幕上还有提醒卡片吗','reminder_get_current'),('现在这张卡片是什么','reminder_get_current'),('音量调到90',None),('假如音量调到90会怎么样',None)]:check('read:'+q,lambda q=q,expected=expected:equal(live_read_request(q),expected))
 for q,expected in [('我爱喝什么','read'),('我就问问爱喝啥，你更正什么记忆啊','read'),('不是啊，我现在不喝咖啡了，你改一下','correct'),('台灯那件事别记着了，忘掉吧','forget'),('别改，我只是问一下','read')]:check('intent:'+q,lambda q=q,expected=expected:equal(memory_intent(q),expected))
 for text,expected in [(json.dumps({'speaker':'甲','content':'我喜欢绿茶'},ensure_ascii=False),'我喜欢绿茶'),(json.dumps({'role':'assistant','content':'我喜欢绿茶'},ensure_ascii=False),''),('我爱喝什么',''),('我喜欢绿茶','我喜欢绿茶')]:check('normalize:'+text,lambda t=text,e=expected:equal(normalize_fact(t),e))
 await vision('already-ready',[{'explain_ready':True}],['vision/status'])
 await vision('refresh-once',[{'explain_ready':False,'explain_reason':'awaiting_initialize'},{'explain_ready':True}],['vision/status','vision/refresh'])
 await vision('closed-no-refresh',[{'explain_ready':False,'explain_reason':'connection_closed'}],['vision/status'])
 await vision('old-session',[{'session_id':'old'}],['vision/status'])
 await vision('connection-replaced',[{'explain_ready':True}],['vision/status'],True)
 def r(tool,state,payload=None):return StepResult(tool=tool,state=state,payload=payload,arguments={},call_id='synthetic',reply='事实')
 for text,result,expected in [('音量调好了，亮度调好了',[r('self_audio_speaker_set_volume','completed',{'volume':20}),r('self_screen_set_brightness','failed')],True),('都搞定了',[r('alarm_set','unknown')],True),('设备重启完成了',[r('self_reboot','accepted')],True),('人脸录入成功了',[r('camera_face_enroll_start','accepted')],True),('已经收到重启请求，是否重启完成还不能确认',[r('self_reboot','accepted')],False),('没有调好音量',[r('self_audio_speaker_set_volume','failed')],False)]:check('claim:'+text,lambda t=text,r=result,e=expected:equal(unsafe(t,r),e))
 from core.utils.voiceprint_provider import VoiceprintProvider
 result={};app=web.Application()
 async def identify(request):return web.json_response(result)
 app.router.add_post('/identify',identify);runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
 provider=VoiceprintProvider.__new__(VoiceprintProvider);provider.enabled=True;provider.api_url=f'http://127.0.0.1:{port}/identify';provider.api_key='test';provider.speaker_ids=['known'];provider.speaker_map={'known':{'name':'已登记人员','user_id':'synthetic'}}
 try:
  for threshold,score,speaker,expected in [(.3,.299,'known',False),(.3,.3,'known',True),(.3,.35,'known',True),(.4,.35,'known',False),(.3,.9,'unknown',False),(.3,.9,'known',True)]:
   name=f'voice-boundary:{threshold}:{score}:{speaker}';budget.reserve('case',name);provider.similarity_threshold=threshold;result.update(score=score,speaker_id=speaker);value=await provider.identify_speaker(b'test-audio','test-session');rows.append({'name':name,'passed':bool(value)==expected,'score':score,'threshold':threshold})
 finally:await runner.cleanup()
 summary={'tests':len(rows),'passed':all(x['passed'] for x in rows),'rows':rows,'budget':budget.report(),'voice_real_recordings':False}
 (stage/'supplement-results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
asyncio.run(main())
