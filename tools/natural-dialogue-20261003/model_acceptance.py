"""Bounded real primary-model acceptance with synthetic dialogue/isolated actions."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio, ast, copy, json, os, re, subprocess, sys, threading, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import yaml, jsonschema
from urllib.request import Request as HttpRequest, urlopen

PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'test'))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
db=yaml.safe_load((PROD.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
match=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(query):
    return subprocess.run(['mysql','--host='+match[1],'--port='+(match[2]or'3306'),'--user='+str(db['username']),
        '--batch','--raw','--skip-column-names',match[3],'-e',query],env=env,capture_output=True,text=True,check=True,timeout=15).stdout.strip()
config=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
assert config['model_name']=='qwen-plus'
key=str(config['api_key']).removeprefix('sk-')
assert re.fullmatch(r'[a-zA-Z0-9_-]+',key)
owner=int(sql("SELECT user_id FROM one_api.tokens WHERE `key`='"+key+"' LIMIT 1;"))
def quota():return int(sql('SELECT used_quota FROM one_api.users WHERE id='+str(owner)+';'))
before=quota()
from core.providers.llm.openai.openai import LLMProvider
provider=LLMProvider(dict(config,timeout=35,max_tokens=220))
provider.client=provider.client.with_options(max_retries=0)
local=yaml.safe_load((PROD/'data/.config.yaml').read_text())
mgr=local['manager-api'];url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
req=HttpRequest(url+'/config/server-base',data=b'{}',method='POST',headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'})
with urlopen(req,timeout=15) as r:base=json.load(r)['data']
PERSONA='你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'
from core.utils.prompt_manager import PromptManager
manager=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock())
candidate=manager.build_enhanced_prompt_v2(PERSONA,'synthetic-acceptance',device_name='小智',user_nickname='主人',official_enhanced=True)
# Fresh baseline built in a separate interpreter with the production modules.
baseline_code="""import os,sys;from unittest.mock import MagicMock;os.chdir(sys.argv[1]);sys.path.insert(0,sys.argv[1]);import config.logger;config.logger.setup_logging=lambda:MagicMock();from core.utils.prompt_manager import PromptManager;print(PromptManager({'system_base_prompt':sys.argv[2],'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(sys.argv[3],'synthetic-acceptance',device_name='小智',user_nickname='主人',official_enhanced=True))"""
baseline=subprocess.run([sys.executable,'-c',baseline_code,str(PROD),base.get('system_base_prompt',''),PERSONA],capture_output=True,text=True,check=True).stdout.strip()
(OUT/'candidate-system.txt').write_text(candidate)
(OUT/'baseline-system.txt').write_text(baseline)
from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
async def inspect_gateway():
    configs=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
    client=ServerMCPClient(next(c for c in configs.values() if not c.get('disabled',False)))
    try:
        await asyncio.wait_for(client.initialize(),20)
        tools=client.get_available_tools()
        result=await asyncio.wait_for(client.call_tool('get_world_time',{'timezone':'Asia/Tokyo'}),15)
        (OUT/'live-gateway.json').write_text(json.dumps({'tools':tools,'read_only_result':result.model_dump(mode='json')},ensure_ascii=False,indent=2))
        return tools
    finally:await client.cleanup()
gateway=asyncio.run(inspect_gateway())
from test_operation_control import definitions
tools=[d.description for d in definitions().values()]+[t for t in gateway if t['function']['name']!='add_reminder']
schemas={t['function']['name']:t['function']['parameters'] for t in tools}
from core.utils.operation_control import OperationControl, CONTRACTS, feedback, Request, guard_reply

cases=[]
def add(text,names,group='action',values=None,without=None):
    cases.append({'id':len(cases)+1,'text':text,'expected':names,'group':group,'values':values or {},'without':without or []})
for noun,value in [('音量',30),('亮度',80)]:
    name='self_audio_speaker_set_volume' if noun=='音量' else 'self_screen_set_brightness'
    key='volume' if noun=='音量' else 'brightness'
    for text in [f'把{noun}调到{value}',f'请将{noun}设置为{value}',f'帮我把{noun}设成{value}',f'{noun}改成{value}',f'麻烦把{noun}调至{value}',f'给我把{noun}设置到{value}',f'把{noun}调整到{value}',f'{noun}设置为{value}',f'请把{noun}设到{value}',f'{noun}调为{value}']:
        add(text,[name],values={key:value})
for text in ['打开摄像头','请打开摄像头预览','开启实时预览','开摄像头','显示实时画面','帮我打开实时画面','请显示摄像头画面']:
    add(text,['camera_open'])
for text in ['关闭摄像头','请关掉摄像头','停止实时预览','关闭摄像头预览','帮我退出预览','关摄像头','停止预览']:
    add(text,['camera_close'])
for text in ['拍一张照片，看看桌上有什么','帮我拍一张照片','请拍照','拍张照片看看杯子是什么颜色','拍一张，看看这个怎么用','拍照描述一下眼前的物品','给我拍张照']:
    add(text,['self_camera_take_photo'])
for text in ['查询设备当前状态','帮我查看当前设备状态','看看设备状态','请查设备现在状态','查询当前音量','查看当前亮度']:
    add(text,['self_get_device_status'])
for text in ['两分钟后提醒我喝水','明天上午九点提醒我开会','半小时后提醒我休息','请五分钟后提醒我站起来','今晚九点提醒我关窗','帮我今天下午三点提醒我带文件','十分钟后提醒我检查炉子']:
    add(text,['add_reminder'])
for text in ['帮我记个便签：出门带伞','请记一下买牛奶','记一条便签：周末买纸巾','给我记下拿钥匙','帮我记录一下水电费要交','记个便签带充电器']:
    add(text,['note_add'])
for text in ['不要打开摄像头','别关闭摄像头','不用拍照','先不把音量调到30','暂不把亮度调到80','如果打开摄像头会怎样','假如把音量设成30呢','他说“拍一张照片”','这句“关闭摄像头”是什么意思','音量是什么','如何调整亮度','先解释预览是什么','不要提醒我喝水','别记便签','我不想拍照','摄像头预览和拍照有啥区别','不用设提醒，我想了解提醒的功能','开摄像头这件事先不做','假设提醒设好以后会怎样','为什么别人会说音量已经调好了']:
    add(text,[],'non_action')
for text in ['打开摄像头','显示实时画面','开启摄像头预览','关闭摄像头','关掉摄像头预览']:
    add(text,[],'unavailable',without=['camera_open','camera_close'])
for text in ['把音量调到30，并把亮度调到80','请把音量设成30，然后关闭摄像头','把亮度调到80，再打开摄像头','把音量调到30，并查询设备状态','把亮度调到80，并拍一张照片']:
    expected=[r for r,word in [('self_audio_speaker_set_volume','音量'),('self_screen_set_brightness','亮度'),('camera_close','关闭摄像头'),('camera_open','打开摄像头'),('self_get_device_status','设备状态'),('self_camera_take_photo','拍一张')] if word in text]
    add(text,expected,'multi')
for text in ['帮我查一下东京现在的时间','查询伦敦现在几点','请列出我手动创建的习惯','查一下手动习惯列表','使用随机工具从红蓝绿里选一个']:
    names=['get_world_time'] if '时间' in text or '几点' in text else ['habit_list_manual'] if '习惯' in text else ['random_decision']
    add(text,names,'mcp')
STYLE=['你好，随便聊聊。','23乘以17等于多少？','解释一下天空为什么是蓝色的。','我今天有点烦，先别开玩笑。','我刚失业，不知道下一步怎么办。','你觉得成年人最难的事情是什么？','我需要认真讨论一个项目方案。','今天累了，不想动脑子。','别哄我，说说你真实的看法。','我和朋友吵架了，怎么把话说清楚？','给我讲一个短故事。','我做事总拖延，你怎么看？','你会怎么回应别人不合理的要求？','人为什么会害怕拒绝别人？','我们能正常聊一会儿吗？','聊聊一个你觉得有意思的科学问题。','我不喜欢你每句话都问我一个问题。','我今天完成了一个一直拖着的任务。','你可以有幽默感，但别撒娇。','如果我不同意你的观点，你会怎么聊？']
for text in STYLE:add(text,[],'style')
assert len(cases)>=100 and len({c['text']+str(c['without']) for c in cases})==len(cases)
(OUT/'semantic-cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2))
if '--style-only' in sys.argv:
    cases=[c for c in cases if c['group']=='style' or c['text']=='音量是什么']
if '--regressions-only' in sys.argv:
    targets=[c for c in cases if c['group']=='unavailable' or c['text'] in
             {'不用拍照','音量是什么','先解释预览是什么','别哄我，说说你真实的看法。'}]
    cases=[dict(c,id=f"{c['id']}-repeat-{repeat}") for repeat in range(1,4) for c in targets]
report={'model':config['model_name'],'persona_preserved':PERSONA in candidate,'prompt_characters':{'baseline':len(baseline),'candidate':len(candidate)},'cases':[],'baseline_style':[],
        'model_calls':0,'budget':{'maximum_calls':150,'maximum_additional_shared_account_quota':1200000,'shared_usage_includes_other_work':True},'device_actions':'isolated; actual hardware tested separately'}
lock=threading.Lock()
def completion(system,case):
    with lock:
        assert report['model_calls']<150,'model_call_guard'
        assert quota()-before<1200000,'quota_guard'
        report['model_calls']+=1
    start=time.perf_counter()
    active=[t for t in tools if t['function']['name'] not in case['without']]
    from core.utils.turn_context import render_turn_context
    context=render_turn_context({'current_datetime':'2026-10-03 12:00:00','today_weekday':'星期六','timezone':'Asia/Shanghai','speaker':'测试用户'})
    messages=[{'role':'system','content':system},{'role':'user','content':context+'\n[用户原话]\n'+case['text']}]
    control=OperationControl();control.begin(case['text'],('s','p'))
    response=provider.client.chat.completions.create(model=provider.model_name,messages=messages,tools=active,tool_choice='none' if system==candidate and control.chat_only else 'auto',
        max_tokens=220,temperature=float(config.get('temperature') or .7),top_p=float(config.get('top_p') or 1),extra_body={'enable_thinking':False})
    message=response.choices[0].message
    calls=[{'name':c.function.name,'arguments':json.loads(c.function.arguments)} for c in message.tool_calls or []]
    text=message.content or ''
    style_flags=[label for label,pattern in [('invalid_stage',r'\[(?:smirk|wink|grin)'),('baby_speech',r'好不好呀|乖乖|小主人|[～~]|嘻嘻|嘿嘿|人家|小尾巴|小脑袋瓜'),('emoji',r'[\U0001F300-\U0001FAFF]'),('imaginary_action',r'[（(](?:眨眼|眨眨眼|歪头|捂嘴|叉腰|偷笑)'),('invented_memory',r'你上一次拖延|刚偷偷.*(?:日程表|档案|算到)')]
                 if re.search(pattern,text,re.I)]
    native_errors=[]
    if set(c['name'] for c in calls)!=set(case['expected']):native_errors.append('native_tool_selection')
    for call in calls:
        try:
            assert call['name'] in {t['function']['name'] for t in active}
            jsonschema.validate(call['arguments'],schemas[call['name']])
            for k,v in case['values'].items():assert call['arguments'].get(k)==v
        except Exception:native_errors.append('native_schema_or_parameter')
    # Actual runtime uses its verified direct plan first. Native errors are still
    # reported separately; a direct route is never counted as native model success.
    control=OperationControl();plan=control.begin(case['text'],('s','p'))
    final=[];runtime_errors=[]
    if plan.requests:
        final=[CONTRACTS[r.kind][0] for r in plan.requests if CONTRACTS[r.kind][0] not in case['without']]
    elif plan.reply:
        final=[]
    else:
        for call in calls:
            if control.validate_intent(call['name'],call['arguments']) is not None:
                continue
            if call['name'] in case['without'] or call['name'] not in schemas:
                continue
            try:jsonschema.validate(call['arguments'],schemas[call['name']])
            except Exception:continue
            final.append(call['name'])
    if set(final)!=set(case['expected']):runtime_errors.append('runtime_tool_selection')
    # Runtime formatting has a separately tested, non-model normalizer. Keep raw
    # flags visible to avoid misreporting the model's own adherence.
    conn=SimpleNamespace(config={'operation_control':{'enabled':True}},_operation_control=control)
    delivered=plan.reply or guard_reply(conn,text)
    delivered_flags=[flag for flag in style_flags if flag not in {'invalid_stage','emoji'}]
    if 'baby_speech' in delivered_flags and not re.search(r'好不好呀|乖乖|小主人|[～~]|嘻嘻|嘿嘿|人家|小尾巴|小脑袋瓜',delivered):delivered_flags.remove('baby_speech')
    if case['group']=='style' and delivered_flags:runtime_errors.append('style')
    return {'id':case['id'],'text':case['text'],'group':case['group'],'expected':case['expected'],
        'native_calls':calls,'native_errors':native_errors,'direct_route':bool(plan.requests or plan.reply),'runtime_calls':final,
        'runtime_errors':runtime_errors,'response':text,'delivered_response':delivered,'style_flags':style_flags,'delivered_style_flags':delivered_flags,'elapsed_seconds':round(time.perf_counter()-start,3),
        'usage':response.usage.model_dump() if response.usage else None}

def save():
    filename='model-failure-revalidation.json' if '--regressions-only' in sys.argv else 'model-acceptance.json'
    (OUT/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2))

with ThreadPoolExecutor(max_workers=3) as pool:
    futures={pool.submit(completion,candidate,c):c for c in cases}
    for future in as_completed(futures):
        c=futures[future]
        try:row=future.result()
        except Exception as exc:row={'id':c['id'],'text':c['text'],'group':c['group'],'runtime_errors':['infrastructure'],'error_type':type(exc).__name__}
        report['cases'].append(row);save()
        if len(report['cases'])%20==0:print('completed',len(report['cases']),flush=True)
for case in ([] if '--style-only' in sys.argv else [c for c in cases if c['group']=='style'][:10]):
    try:report['baseline_style'].append(completion(baseline,case))
    except Exception as exc:report['baseline_style'].append({'error_type':type(exc).__name__})
    save()
report['shared_account_quota_delta']=quota()-before
report['summary']={'cases':len(report['cases']),'runtime_pass':sum(not r['runtime_errors'] for r in report['cases']),
    'native_pass':sum(not r.get('native_errors',['error']) for r in report['cases']),
    'style_flagged':sum(bool(r.get('delivered_style_flags')) for r in report['cases'] if r['group']=='style'),
    'baseline_style_flagged':sum(bool(r.get('style_flags')) for r in report['baseline_style'])}
report['success']=report['summary']['runtime_pass']/len(report['cases'])>=.95 and report['summary']['style_flagged']==0
save();print(json.dumps({'summary':report['summary'],'success':report['success'],'prompt_characters':report['prompt_characters'],'model_calls':report['model_calls']}))
