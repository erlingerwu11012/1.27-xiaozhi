"""Real configured model and MCP metadata; device actions use an isolated transport.

No production prompt/config writes, customer histories, or live device controls.
Only get_world_time is actually executed against the existing MCP gateway.
"""
from __future__ import annotations

import asyncio
import ast
import copy
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import jsonschema
import yaml

ROOT = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT = Path('/root/prjs/tmp/prompt-mcp-test-20261003')
OUT.mkdir(exist_ok=True)
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import config.logger as logging_config
logging_config.setup_logging = lambda: MagicMock()

payload = json.loads((OUT / 'payload.json').read_text())
report = {'mode': 'real_model_with_mock_device_actions', 'model_calls': 0,
          'live_mcp': {}, 'cases': [], 'continuations': [], 'protocol': [],
          'production_config_changed': False, 'device_actions_executed': False,
          'customer_history_read': False, 'started_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

def save():
    (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

db = yaml.safe_load(Path('/root/prjs/xiaozhi-esp32-server/main/manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
match = re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)', db['url'])
db_env = dict(os.environ, MYSQL_PWD=str(db['password']))

def sql(query):
    return subprocess.run(['mysql', '--host='+match[1], '--port='+(match[2] or '3306'),
                           '--user='+str(db['username']), '--batch', '--raw', '--skip-column-names',
                           match[3], '-e', query], env=db_env, capture_output=True, text=True,
                          check=True, timeout=15).stdout.strip()

model_config = json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
assert model_config['model_name'] == 'qwen-plus'
from urllib.parse import urlparse
assert urlparse(model_config.get('base_url') or model_config.get('url')).hostname in {'127.0.0.1', 'localhost'}
key = str(model_config['api_key']).removeprefix('sk-')
token_owner = None
if re.fullmatch(r'[a-zA-Z0-9_-]+', key):
    owner = sql("SELECT user_id FROM one_api.tokens WHERE `key`='" + key + "' LIMIT 1;")
    token_owner = int(owner) if owner else None

def quota():
    return int(sql('SELECT used_quota FROM one_api.users WHERE id='+str(token_owner)+';')) if token_owner else None

quota_before = quota()
report['quota_guard'] = {'max_model_calls': 48, 'max_additional_shared_account_quota': 200000,
                         'shared_account_usage_is_not_test_only': True}
from core.providers.llm.openai.openai import LLMProvider
provider = LLMProvider(dict(model_config, timeout=35, max_tokens=384))
provider.client = provider.client.with_options(max_retries=0)

def completion(label, messages, tools=None):
    assert report['model_calls'] < 48, 'model_call_guard'
    current = quota()
    assert current is None or quota_before is None or current-quota_before < 200000, 'quota_guard'
    report['model_calls'] += 1
    start = time.perf_counter()
    kwargs = dict(model=provider.model_name, messages=messages, max_tokens=384,
                  temperature=float(model_config.get('temperature') or 0.7),
                  top_p=float(model_config.get('top_p') or 1), extra_body={'enable_thinking': False})
    if tools:
        kwargs.update(tools=tools, tool_choice='auto')
    response = provider.client.chat.completions.create(**kwargs)
    return response.choices[0].message, response.usage.model_dump() if response.usage else None, round(time.perf_counter()-start, 3)

from core.providers.tools.server_mcp.mcp_client import ServerMCPClient

async def inspect_live_mcp():
    configs = json.loads((ROOT / 'data/.mcp_server_settings.json').read_text())['mcpServers']
    cfg = next(c for c in configs.values() if not c.get('disabled', False))
    client = ServerMCPClient(cfg)
    try:
        await asyncio.wait_for(client.initialize(), 20)
        tools = client.get_available_tools()
        result = await asyncio.wait_for(client.call_tool('get_world_time', {'timezone': 'Asia/Tokyo'}), 15)
        report['live_mcp'] = {'initialize': True, 'tools_list': True,
                              'tool_names': [x['function']['name'] for x in tools],
                              'read_only_call': 'get_world_time',
                              'read_only_arguments': {'timezone': 'Asia/Tokyo'},
                              'read_only_result': result.model_dump(mode='json') if hasattr(result, 'model_dump') else str(result)}
        (OUT / 'gateway-tools.json').write_text(json.dumps(tools, ensure_ascii=False, indent=2))
        save()
        return tools
    finally:
        await client.cleanup()

gateway_tools = asyncio.run(inspect_live_mcp())
from core.providers.tools.device_mcp.mcp_client import MCPClient
from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
from core.utils.device_reminder import rewrite_reminder_tool_descriptions

device_fixture = json.loads((ROOT / 'test/js/config/default-mcp-tools.json').read_text())
device_fixture += [
    # These preview capabilities are test fixtures from test_camera_mcp_tools.py,
    # not a claim that the connected user's current firmware exposes preview.
    {'name':'camera.open','description':'打开摄像头实时预览，不拍照；只有明确开启要求才调用。','inputSchema':{'type':'object','properties':{}}},
    {'name':'camera.close','description':'关闭摄像头实时预览。','inputSchema':{'type':'object','properties':{}}},
    {'name':'self.camera.take_photo','description':'仅在用户明确要求拍一张静态照片并识别画面内容时调用；此工具只拍摄一帧并上传识别，不能代替打开预览。','inputSchema':{'type':'object','properties':{'question':{'type':'string'}},'required':['question']}},
    {'name':'note.add','description':'添加备忘录卡片。定时提醒请通过add_reminder处理。','inputSchema':{'type':'object','properties':{'text':{'type':'string'},'remind_at':{'type':'integer'},'user_id':{'type':'string'}},'required':['text','remind_at']}},
]

async def get_device_functions(raw):
    client = MCPClient('synthetic-prompt-test', 'test-firmware', 'test-session')
    for definition in raw:
        await client.add_tool(definition)
    await client.set_ready(True)
    conn = SimpleNamespace(mcp_client=client)
    tools = rewrite_reminder_tool_descriptions(copy.deepcopy(gateway_tools+client.get_available_tools()), conn)
    return client, tools

device_client, normal_tools = asyncio.run(get_device_functions(device_fixture))
from plugins_func.functions.get_weather import GET_WEATHER_FUNCTION_DESC
normal_tools.append(copy.deepcopy(GET_WEATHER_FUNCTION_DESC))
definitions = {x['function']['name']: x['function'] for x in normal_tools}
report['tool_fixture'] = {'gateway': 'real live tools/list',
                          'device': 'repository default-mcp-tools.json and isolated capability fixtures',
                          'plugin': 'actual get_weather definition',
                          'total_tools': len(normal_tools),
                          'device_capabilities_are_not_live_device_snapshot': True}

# Baseline comes from current server-base configuration and current production builder.
from urllib.request import Request, urlopen
local = yaml.safe_load((ROOT / 'data/.config.yaml').read_text()) or {}
mgr = local['manager-api']; base_url = mgr['url'].rstrip('/')
if '/xiaozhi' not in base_url: base_url += '/xiaozhi'
req = Request(base_url+'/config/server-base', data=b'{}', method='POST',
              headers={'Authorization':'Bearer '+mgr['secret'], 'Content-Type':'application/json'})
with urlopen(req, timeout=15) as response: server_base = json.load(response)['data']
from core.utils.prompt_manager import PromptManager
manager = PromptManager({'system_base_prompt':server_base.get('system_base_prompt',''), 'language':'中文'}, logger=MagicMock())
baseline = manager.build_enhanced_prompt_v2(payload['personality'], 'synthetic-prompt-test', device_name='小智', official_enhanced=True)
slim = '\n\n'.join([payload['core'],payload['speech'],payload['personality'],payload['identity']])
systems = {'baseline':baseline, 'slim':slim}
report['system_characters'] = {name:len(value) for name,value in systems.items()}
context = '[本轮上下文]\n时间:2026-10-03 12:00:00星期六\n时区:Asia/Shanghai\n当前说话人:测试用户\n设备当前音量:50\n设备当前亮度:80\n这是合成测试上下文。'

cases = [
    {'id':'greeting','text':'你好，今天想随便聊聊。','expected':[]},
    {'id':'explain','text':'解释一下为什么天空看起来是蓝色的。','expected':[]},
    {'id':'arithmetic','text':'23乘以17等于多少？','expected':[]},
    {'id':'camera_open','text':'打开摄像头，显示实时预览。','expected':['camera_open']},
    {'id':'camera_close','text':'关闭摄像头预览。','expected':['camera_close']},
    {'id':'photo','text':'拍一张照片，看看桌上有什么。','expected':['self_camera_take_photo']},
    {'id':'camera_negation','text':'不要打开摄像头，我只想知道摄像头预览是什么。','expected':[]},
    {'id':'volume','text':'把音量设置为30。','expected':['self_audio_speaker_set_volume']},
    {'id':'brightness','text':'把屏幕亮度设置为40。','expected':['self_screen_set_brightness']},
    {'id':'status','text':'查询一下设备当前状态。','expected':['self_get_device_status']},
    {'id':'reminder','text':'两分钟后提醒我喝水。','expected':['add_reminder']},
    {'id':'plain_note','text':'帮我记个便签：出门带雨伞。不设定时提醒。','expected':['note_add']},
    {'id':'world_time','text':'帮我查询东京现在的当地时间。','expected':['get_world_time']},
    {'id':'random_pick','text':'用随机工具帮我在红色和蓝色中随机选一个。','expected':['random_decision']},
    {'id':'habit_create','text':'创建一个每天上午9点喝水的习惯提醒，提前2分钟。','expected':['habit_create']},
    {'id':'habit_list','text':'查询我手动创建的习惯列表。','expected':['habit_list_manual']},
    {'id':'camera_unavailable','text':'打开摄像头，显示实时预览。','expected':[], 'without':['camera_open','camera_close']},
    {'id':'multiple','text':'把音量设为30，并查询东京现在几点。','expected':['self_audio_speaker_set_volume','get_world_time']},
]

def calls_of(msg):
    calls=[]
    for call in msg.tool_calls or []:
        calls.append({'id':call.id,'name':call.function.name,'arguments':json.loads(call.function.arguments)})
    return calls

def validate_case(case,calls):
    names=[c['name'] for c in calls]
    errors=[]
    if set(names)!=set(case['expected']):errors.append('tool_selection')
    for call in calls:
        try:jsonschema.validate(call['arguments'], definitions[call['name']]['parameters'])
        except Exception:errors.append('parameter_schema')
    for call in calls:
        name,args=call['name'],call['arguments']
        if name=='self_audio_speaker_set_volume' and args.get('volume')!=30:errors.append('volume_value')
        if name=='self_screen_set_brightness' and args.get('brightness')!=40:errors.append('brightness_value')
        if name=='get_world_time' and args.get('timezone')!='Asia/Tokyo':errors.append('timezone_value')
        if name=='add_reminder':
            text=str(args.get('text',''))+str(args.get('remind_time_str',''))
            if not ('两分钟' in text or '2分钟' in text):errors.append('natural_language_time')
            if not '喝水' in str(args):errors.append('reminder_content')
            if any(k in args for k in ['timestamp','remind_at','user_id']):errors.append('invented_reminder_fields')
        if name=='note_add' and args.get('remind_at')!=0:errors.append('plain_note_time')
        if name=='habit_create' and (args.get('hour')!=9 or args.get('advance_minutes')!=2):errors.append('habit_time')
        if name=='random_decision' and (args.get('mode')!='pick' or not all(x in str(args.get('options')) for x in ['红色','蓝色'])):errors.append('random_options')
    return sorted(set(errors))

messages_by_case={}
for case in cases:
    tools=[t for t in normal_tools if t['function']['name'] not in case.get('without',[])]
    for variant,system in systems.items():
        messages=[{'role':'system','content':system},{'role':'user','content':context+'\n'+case['text']}]
        try:
            msg,usage,elapsed=completion(variant+':'+case['id'],messages,tools)
            calls=calls_of(msg);errors=validate_case(case,calls)
            row={'variant':variant,'case':case['id'],'input':case['text'],'expected':case['expected'],
                 'calls':calls,'text':msg.content,'passed':not errors,'errors':errors,'usage':usage,'seconds':elapsed}
            messages_by_case[(variant,case['id'])]=(messages,msg,tools)
        except Exception as exc:
            row={'variant':variant,'case':case['id'],'passed':False,'errors':['request_error'],
                 'error_type':type(exc).__name__,'http_status':getattr(exc,'status_code',None)}
        report['cases'].append(row);save()
        print('CASE',variant,case['id'],'PASS' if row['passed'] else 'FAIL',row.get('errors'),flush=True)

# Follow-up answers use explicitly simulated results; no live writes occur.
for case_id,outcome in [('volume','success'),('reminder','failure'),('world_time','success')]:
    triple=messages_by_case.get(('slim',case_id))
    if not triple:continue
    messages,msg,tools=triple;calls=calls_of(msg)
    if not calls:continue
    answer_messages=copy.deepcopy(messages)+[msg.model_dump(exclude_none=True)]
    for call in calls:
        if outcome=='failure':body={'status':'error','errorCode':'connection_closed','message':'设备已离线，本次提醒未创建。'}
        elif case_id=='volume':body={'status':'success','volume':30}
        else:body=report['live_mcp']['read_only_result']
        answer_messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(body,ensure_ascii=False)})
    final,usage,elapsed=completion('continuation:'+case_id,answer_messages,tools)
    text=final.content or '';final_calls=calls_of(final)
    if outcome=='failure':passed=not final_calls and any(w in text for w in ['未','没','失败','无法','离线','不能'])
    elif case_id=='volume':passed=not final_calls and '30' in text
    else:passed=not final_calls and bool(text)
    report['continuations'].append({'case':case_id,'outcome':outcome,'passed':passed,
                                    'text':text,'calls':final_calls,'usage':usage,'seconds':elapsed})
    save();print('CONTINUATION',case_id,'PASS' if passed else 'FAIL',flush=True)

class SyntheticSocket:
    def __init__(self,client):self.client=client;self.messages=[]
    async def send(self,text):
        data=json.loads(text);self.messages.append(data)
        data=data.get('payload',{})
        if data.get('method')=='tools/call':
            await self.client.resolve_call_result(data['id'],{'content':[{'type':'text','text':'{"status":"success"}'}]})

async def protocol_dispatch():
    client,_=await get_device_functions(device_fixture)
    ws=SyntheticSocket(client)
    conn=SimpleNamespace(mcp_client=client,websocket=ws,features={'mcp':True},device_id='synthetic-prompt-test',
                         session_id='test-session',headers={},logger=MagicMock(),last_activity_time=0.0)
    for row in report['cases']:
        if row['variant']!='slim':continue
        for call in row.get('calls',[]):
            if call['name'] not in client.tools:continue
            before=len(ws.messages)
            try:
                result=await call_mcp_tool(conn,client,call['name'],json.dumps(call['arguments']),timeout=2)
                emitted=ws.messages[before:]
                actual=[x['payload']['params']['name'] for x in emitted if x.get('payload',{}).get('method')=='tools/call']
                expected=client.name_mapping[call['name']]
                passed=actual==[expected]
                report['protocol'].append({'case':row['case'],'model_name':call['name'],'raw_mcp_name':expected,
                                           'emitted_names':actual,'passed':passed,'transport':'synthetic websocket'})
            except Exception as exc:
                report['protocol'].append({'case':row['case'],'model_name':call['name'],'passed':False,'error_type':type(exc).__name__})
    save()

asyncio.run(protocol_dispatch())
report['summary']={variant:{'passed':sum(x['passed'] for x in report['cases'] if x['variant']==variant),
                            'total':sum(x['variant']==variant for x in report['cases'])} for variant in systems}
report['summary']['continuations']={'passed':sum(x['passed'] for x in report['continuations']),'total':len(report['continuations'])}
report['summary']['mock_mcp_dispatch']={'passed':sum(x['passed'] for x in report['protocol']),'total':len(report['protocol'])}
report['usage_totals']={key:sum((x.get('usage') or {}).get(key,0) for x in report['cases']+report['continuations']) for key in ['prompt_tokens','completion_tokens','total_tokens']}
report['quota_usage_delta_shared_account']=None if quota_before is None else quota()-quota_before
report['finished_at_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
save();provider.client.close()
print('SUMMARY',json.dumps(report['summary'],ensure_ascii=False),flush=True)
