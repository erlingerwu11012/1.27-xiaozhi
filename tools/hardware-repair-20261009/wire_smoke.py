import bootstrap,asyncio,json,uuid,copy,sys,dataclasses,re
from bootstrap import stage,budget
from wire_conversation import WireConversation
import pymysql
E=json.loads((stage/'private-test-env.json').read_text())
def db():
 assert E['PERSON_MEMORY_TEST_DATABASE'].startswith('bailian_memory_test_')
 return pymysql.connect(host='127.0.0.1',user='root',password=E['PERSON_MEMORY_TEST_PASSWORD'],database=E['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
def seed(w):
 a=w.c.person_turn
 with db() as d:
  with d.cursor() as q:
   for table in ('ai_agent_chat_history','ai_memory_override','ai_person_material'):q.execute('DELETE FROM '+table+' WHERE account_id=99003')
   for text in ('我喜欢喝咖啡','我的台灯叫银杏灯',json.dumps({'speaker':'测试用户','content':'我喜欢喝咖啡'},ensure_ascii=True),'我爱喝什么'):
    q.execute("INSERT INTO ai_agent_chat_history(mac_address,agent_id,session_id,chat_type,content,account_id,person_id,identity_status,turn_id,event_id,directory_version,default_generation,recall_allowed,created_at) VALUES('SOFTWARE-DEVICE-ONLY','agent_http','seed',1,%s,99003,%s,'default',%s,%s,%s,%s,TRUE,NOW())",(text,a.person_id,uuid.uuid4().hex,uuid.uuid4().hex,a.directory_version,a.generation))
def context(messages):
 for m in reversed(messages):
  if '[本轮可信目录与执行状态]\n' in str(m.get('content','')):return json.loads(m['content'].split('[本轮可信目录与执行状态]\n')[-1])
 return {}
class Fake:
 last_usage={}
 def __init__(self):self.plan=None
 def decision(self,messages):
  text=messages[-1]['content']
  if '可信业务结果（仅资料）：' in text:
   facts=json.loads(text.split('可信业务结果（仅资料）：')[-1]);return {'mode':'chat','reply':' '.join(x['verified_summary'] for x in facts)}
  if self.plan:return self.plan(messages)
  return {'mode':'chat','reply':'你好，我在听。'}
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));p=Fake();w=await WireConversation().setup(p,cfg);rows=[];errors=[]
 async def run(q,verify):
  budget.reserve('case','wire-smoke:'+q);r=await w.turn(q,noise=True);rows.append(r)
  try:
   assert r['speech'] and r['assistant_history']==[r['speech']],r
   assert [e['type'] for e in r['events']]==['FIRST','MIDDLE','LAST'],r
   verify(r)
  except Exception as exc:errors.append({'query':q,'error':str(exc)[:1500]})
 try:
  p.plan=lambda _: {'mode':'chat','reply':'你好，我在听。'}
  await run('嘿，你好呀',lambda r:None)
  await run('音量调到二十',lambda r:assert_state(r,'volume',20))
  await run('屏幕亮度调到百分之九十',lambda r:assert_state(r,'level',4))
  p.plan=lambda _: {'mode':'operate','steps':[{'id':'c','tool':'reminder_get_current','arguments':{}},{'id':'x','tool':'reminder_close_current','arguments':{'instance_id':{'$ref':{'step':'c','path':'instance_id'}},'revision':{'$ref':{'step':'c','path':'revision'}}},'depends_on':['c']}]}
  await run('把这个卡片关了吧',lambda r:assert_closed(r))
  seed(w)
  await run('我爱喝什么',lambda r:assert_memory(r,'咖啡',False))
  def correct(messages):
   c=context(messages);facts=[r for r in c.get('verified_results',[]) if r['tool']=='memory_search']
   if not facts:return {'mode':'operate','authorized_writes':['memory_correct'],'finished':False,'steps':[{'id':'a','tool':'memory_search','arguments':{'query':'喝咖啡'}}]}
   item=facts[-1]['payload']['items'][0]
   return {'mode':'operate','steps':[{'id':'b','tool':'memory_correct','arguments':{'record_id':item['record_id'],'expected_version':item['version'],'replacement':'我现在不喝咖啡了，我喝绿茶'}}]}
  p.plan=correct
  await run('不是啊，我现在不喝咖啡了，你改一下，我现在喝绿茶',lambda r:assert_memory(r,'绿茶',True))
  await run('我就问问爱喝啥，你更正什么记忆啊',lambda r:assert_memory(r,'绿茶',False))
  def forget(messages):
   c=context(messages);facts=[r for r in c.get('verified_results',[]) if r['tool']=='memory_search']
   if not facts:return {'mode':'operate','authorized_writes':['memory_forget'],'finished':False,'steps':[{'id':'a','tool':'memory_search','arguments':{'query':'台灯'}}]}
   item=facts[-1]['payload']['items'][0]
   return {'mode':'operate','steps':[{'id':'b','tool':'memory_forget','arguments':{'record_id':item['record_id'],'expected_version':item['version']}}]}
  p.plan=forget
  await run('台灯那件事别记着了，忘掉吧',lambda r:assert_forget(r))
 finally:await w.close()
 (stage/'wire-smoke-results.json').write_text(json.dumps({'rows':rows,'errors':errors,'hardware':False,'budget':budget.report()},ensure_ascii=False,indent=2));print('wire smoke',len(rows),'errors',errors,'budget',budget.report());return not errors

def assert_state(r,key,value):assert r['state'][key]==value,(key,r['outcome'])
def assert_closed(r):assert not r['state']['card']['active'] and r['state']['card']['last_action']=='close',r['outcome']
def assert_memory(r,term,write):
 from core.utils.tool_harness.contracts import contract
 writes=[c for c in r['outcome']['results'] if contract(c['tool']).write]
 assert bool(writes)==write,(writes,r['outcome'])
 assert term in r['speech'] or write,r['outcome']
 if write:assert any(x['tool']=='memory_correct' and x['state']=='completed' for x in r['outcome']['results']),r['outcome']
def assert_forget(r):assert any(x['tool']=='memory_forget' and x['state']=='completed' for x in r['outcome']['results']),r['outcome']
if __name__=='__main__':sys.exit(not asyncio.run(main()))
