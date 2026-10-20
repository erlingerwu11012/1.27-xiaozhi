import bootstrap,asyncio,json,copy
from bootstrap import stage,budget
from wire_conversation import WireConversation
from wire_smoke import Fake,context
from core.utils.tool_harness.reply_composer import unsafe
from core.utils.tool_harness.models import StepResult
from core.utils.recipient_resolver import extract_recipient_selector_from_text
rows=[]
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg)
 async def run(q,planner,check):
  budget.reserve('case','targeted:'+q);p.plan=planner;r=await w.turn(q,noise=True)
  try:check(r);rows.append({'query':q,'passed':True,'speech':r['speech'],'outcome':r['outcome']})
  except Exception as exc:rows.append({'query':q,'passed':False,'error':repr(exc),'result':r})
 def assert_set(r,v):assert r['state']['volume']==v and any(x['tool']=='self_audio_speaker_set_volume' and x['state']=='completed' for x in r['outcome']['results']),r['outcome']
 try:
  await run('声音改成九成半吧',lambda m:{'mode':'operate','steps':[{'id':'set','tool':'self_audio_speaker_set_volume','arguments':{'volume':95}}]},lambda r:assert_set(r,95))
  def correct_relative(m):
   c=context(m)
   return {'mode':'operate','steps':[{'id':'s','tool':'self_audio_speaker_set_volume','arguments':{},'relative':10}]} if c.get('validation_error') else {'mode':'operate','steps':[{'id':'read','tool':'self_get_device_status','arguments':{}}]}
  await run('帮我把音量往上加十个点',correct_relative,lambda r:assert_set(r,100))
  def alarm_check(r):assert len(r['state']['alarms'])==1 and r['outcome']['results'][-1]['state']=='completed',r['outcome']
  await run('帮我给我定一个晚上十点的闹钟',lambda m:{'mode':'operate','steps':[{'id':'a','tool':'alarm_set','arguments':{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}}]},alarm_check)
  def clarify_check(r):assert r['outcome']['mode']=='clarify' and not any(x['tool']=='alarm_set' for x in r['outcome']['results']) and ('上午' in r['speech'] or '早上' in r['speech']),r['outcome']
  for q in ['工作日七点半设一个闹钟','每天六点设个闹钟','保存每天8点的喝水习惯']:await run(q,lambda m:{'mode':'chat','reply':'错误注入，不应调用模型'},clarify_check)
  await run('今晚十点钟叫醒我，给我定个闹钟',lambda m:{'mode':'operate','steps':[{'id':'a','tool':'alarm_set','arguments':{'hour':22,'minute':0,'label':'闹钟','repeat_days':0}}]},lambda r:assert_alarm(r))
 finally:await w.close()
 for q,e in [('帮我给我定一个晚上十点的闹钟','我'),('帮我给爸爸设置闹钟','爸爸'),('给妈妈设置提醒','妈妈')]:
  budget.reserve('case','targeted-recipient:'+q);rows.append({'query':q,'passed':extract_recipient_selector_from_text(q)==e})
 budget.reserve('case','query-cannot-claim-setting')
 r=StepResult(tool='self_get_device_status',state='completed',arguments={},payload={'audio_speaker':{'volume':50}},call_id='test',reply='50')
 rows.append({'query':'read-claim','passed':unsafe('好的，音量已从50调至60。',[r])})
 summary={'tests':len(rows),'passed':all(r['passed'] for r in rows),'rows':rows,'budget':budget.report()};(stage/'targeted-results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
def assert_alarm(r):assert r['outcome']['mode']!='clarify' and r['state']['alarms'][-1]['hour']==22,r['outcome']
asyncio.run(main())
