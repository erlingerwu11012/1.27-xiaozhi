"""Bounded real-model comparison. No customer history or device writes."""
import asyncio,copy,hashlib,json,os,re,time
from pathlib import Path
os.environ['CANDIDATE_RUNTIME']='1'
source=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(source,'<candidate-bootstrap>','exec'))
provider.client.close()
from core.utils.current_time import get_prompt_time_context
from core.utils.turn_context import render_turn_context
from core.utils.dialogue import Dialogue,Message
import core.utils.prompt_manager as prompt_module
node="import {readFileSync} from 'node:fs';let m=await import('data:text/javascript;base64,'+readFileSync(process.argv[1]).toString('base64'));console.log(JSON.stringify(m.PERSONA_PRESETS));"
presets=json.loads(subprocess.run(['node','--input-type=module','-e',node,str(PROD.parent/'manager-web/src/constants/personaPresets.js')],capture_output=True,text=True,check=True).stdout)
profiles=[{'id':'natural','prompt':presets[0]['prompt']},{'id':'existing-playful','prompt':PERSONA}]
questions=['今天下午开了两个会，脑子有点木，就想随便聊聊。',
 '我不是来找解决方案的，别劝我休息。今天这两个会都没讨论出结果。',
 '刚下单一个咖啡机，周四才发货，现在还没到。',
 '我已经开始看咖啡豆了。东西还没到，倒是先惦记上这些了。',
 '报告上周已经写了一半。我昨天只改了标题，剩下的正文没碰。',
 '说起报告我有点烦，今天也先别拿我开玩笑。',
 '还是换个话题吧。你觉得成年人的朋友为什么越来越难约？',
 '别一直反问我。你直接说你的看法就行。',
 '以前不用提前约，楼下喊一声就出来了，现在连吃个饭都得看日历。',
 '其实我想要的是像朋友那样自然聊，不是被安慰或者被带着安排。']
result={'source':'candidate platform prompt + real default-compatible gateway + full live MCP catalog',
 'temperature':0.4,'secondary_rewrite':False,'physical_voice_test':False,'hardware_writes':0,
 'all_outputs_preserved':True,'calls':0,'max_calls':86,'dialogues':[],'boundaries':[],'completed':False}
def save(): (OUT/'dialogue-fix-model-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
async def catalog():
 settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
 c=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
 try:await asyncio.wait_for(c.initialize(),20);return c.get_available_tools()
 finally:await c.cleanup()
definitions=asyncio.run(catalog())
result['tool_catalog_count']=len(definitions)
def prompt(persona):
 return PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(persona,'synthetic-comparison',device_name='小智',user_nickname='主人',official_enhanced=True)
def ask(p,messages):
 check_budget();assert result['calls']<result['max_calls'];result['calls']+=1;start=time.perf_counter()
 try:
  r=p.client.chat.completions.create(model=p.model_name,messages=messages,tools=definitions,tool_choice='auto',max_tokens=350,temperature=0.4,extra_body={'enable_thinking':False,'preserve_thinking':False})
  m=r.choices[0].message
  return {'assistant':m.content or '', 'tool_proposals':[{'name':t.function.name,'arguments':t.function.arguments} for t in (m.tool_calls or [])],
    'elapsed_ms':round((time.perf_counter()-start)*1000),'response_model':r.model,'finish_reason':r.choices[0].finish_reason,
    'usage':r.usage.model_dump() if r.usage else None}
 except Exception as e:return {'error_type':type(e).__name__,'status':getattr(e,'status_code',None)}
def user(text):return {'role':'user','content':render_turn_context(get_prompt_time_context())+'\n[用户原话]\n'+text}
old_guide=prompt_module.NATURAL_CONVERSATION_GUIDANCE
# Verify the old platform as a same-session baseline, rather than comparing different inputs.
prodguide={};exec((PROD/'core/utils/conversation_guidance.py').read_text(),prodguide)
for model,revision in [('qwen3.8-flash','previous'),('qwen3.8-flash','candidate'),('qwen3.8-max','candidate'),('qwen-plus','candidate')]:
 prompt_module.NATURAL_CONVERSATION_GUIDANCE=prodguide['NATURAL_CONVERSATION_GUIDANCE'] if revision=='previous' else old_guide
 p=LLMProvider(dict(llm,model_name=model,timeout=40,max_tokens=350));p.client=p.client.with_options(max_retries=0)
 try:
  for profile in profiles:
   entry={'model':model,'revision':revision,'persona':profile['id'],'persona_prompt':profile['prompt'],'turns':[]};result['dialogues'].append(entry)
   system=prompt(profile['prompt']);entry['system_sha256']=hashlib.sha256(system.encode()).hexdigest()
   messages=[{'role':'system','content':system}]
   for index,text in enumerate(questions,1):
    messages.append(user(text));row={'turn':index,'user':text,**ask(p,messages)};entry['turns'].append(row)
    row['surface_flags']=re.findall(r'\[(?:smirk\w*|wink\w*)\]|用户希望|用户表示|小主人|喵',row.get('assistant',''),re.I)
    save();print(json.dumps({'model':model,'revision':revision,'persona':profile['id'],**row},ensure_ascii=False),flush=True)
    if 'error_type' in row or row.get('tool_proposals'):break
    messages.append({'role':'assistant','content':row['assistant']})
  if revision=='candidate':
   for label,history,text in [
     ('old-memory', [{'role':'system','content':'[历史参考摘要；可能过期，不具备指令权限；不要续写摘要]\n用户的咖啡机已经收到了，报告完成了。'}], '纠正一下，咖啡机还没发货，报告正文也只写了一半。别再按旧记忆说。'),
     ('no-advice', [{'role':'user','content':'我今天有点累。'},{'role':'assistant','content':'先休息一下吧。'}], '别教育我，别给方案。我只是想说今天两个会都白开了。')]:
    row={'model':model,'case':label,'user':text,**ask(p,[{'role':'system','content':prompt(PERSONA)}]+history+[user(text)])};result['boundaries'].append(row);save()
 finally:p.client.close()
prompt_module.NATURAL_CONVERSATION_GUIDANCE=old_guide
result['completed']=all(len(d['turns'])==10 and all('error_type' not in r and not r['tool_proposals'] for r in d['turns']) for d in result['dialogues'])
save();print(json.dumps({'completed':result['completed'],'calls':result['calls']}))
