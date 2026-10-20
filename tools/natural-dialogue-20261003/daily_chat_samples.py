"""Eight real primary-model text turns, current device settings, no history writes."""
import hashlib, json, os, subprocess, sys, time, uuid
from pathlib import Path
from unittest.mock import MagicMock

ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
DEVICE='ac:a7:04:fd:20:2c'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
processes=json.loads(subprocess.run(['pm2','jlist'],check=True,capture_output=True,text=True).stdout)
proc=next(p for p in processes if p['name']=='xiaozhi-server')
assert proc['pm2_env']['status']=='online'
for part in Path('/proc/'+str(proc['pid'])+'/environ').read_bytes().split(b'\0'):
    if b'=' in part:
        key,value=part.split(b'=',1)
        if key.startswith(b'HW_BILLING_') or key==b'AGENT_PERSONAS_DIR':
            os.environ[key.decode()]=value.decode()
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from config.settings import load_config
from config.config_loader import get_private_config_from_api
from core.utils.prompt_manager import PromptManager
from core.utils.current_time import get_prompt_time_context
from core.utils.turn_context import render_turn_context
from core.utils import llm as llm_utils

base=load_config()
private=get_private_config_from_api(base,DEVICE,DEVICE)
selected=private['selected_module']['LLM']
llm_config=dict(private['LLM'][selected]);llm_config['_config_name']=selected
assert llm_config.get('type','openai')=='openai','unexpected provider; inspect before testing'
persona=private.get('prompt')
assert isinstance(persona,str) and persona.strip(),'device persona missing'
name=private.get('device_name') or '小智'
tts_selected=private['selected_module'].get('TTS')
tts_config=private.get('TTS',{}).get(tts_selected,{})
tts_type=str(tts_config.get('type') or tts_selected or '')
official=tts_type in {'official','qwen_audio_tts_plus'} or 'official' in tts_type.lower()
system=PromptManager(base,logger=MagicMock()).build_enhanced_prompt_v2(
    persona,DEVICE,device_name=name,user_nickname=private.get('user_nickname','用户'),official_enhanced=official)
provider=llm_utils.create_instance('openai',dict(llm_config,timeout=45))
provider.client=provider.client.with_options(max_retries=0)
# Transport errors are reported once. Generation parameters remain device defaults.
provider._create_with_retry=provider.client.chat.completions.create
scenes=[
    ('下班闲聊', ['今天累了一天，啥也不想干。','别给我灌鸡汤，也别给方案，就随便聊两句。','我点了外卖，吃完洗澡，然后躺着。']),
    ('拖延与接话', ['本来想今天把方案写完，结果刷手机刷到现在。','你这话听着像我领导，别教育我。','那你说，我今晚还做不做？']),
    ('轻松调侃', ['我打算周末把家里彻底收拾一遍。','说实话，我每次都这么说，最后就收拾个桌面。'])]
report={'source':'real default primary LLM; current production prompt and device persona',
        'selected_llm':selected,'model':provider.model_name,'assistant_name':name,
        'persona':persona,'persona_sha256':hashlib.sha256(persona.encode()).hexdigest(),
        'official_expression_rules':official,'system_characters':len(system),
        'text_only':True,'asr_used':False,'tts_used':False,'tools_executed':0,
        'retrieved_customer_history':False,'secondary_rewrite':False,'model_calls':0,'maximum_calls':8,
        'generation_parameters':{k:getattr(provider,k,None) for k in ['temperature','top_p','max_tokens']},'scenes':[]}
session='daily-sample-'+uuid.uuid4().hex
for title,inputs in scenes:
    messages=[{'role':'system','content':system}]
    rows=[]
    for text in inputs:
        assert report['model_calls']<8
        context=render_turn_context(get_prompt_time_context())
        messages.append({'role':'user','content':context+'\n[用户原话]\n'+text})
        report['model_calls']+=1;start=time.perf_counter()
        answer=''.join(str(part or '') for part in provider.response(session,messages))
        row={'user':text,'assistant':answer,'elapsed_ms':round((time.perf_counter()-start)*1000),
             'usage':provider.last_usage,'error':getattr(provider._usage_local,'error',None)}
        rows.append(row);messages.append({'role':'assistant','content':answer})
        print(json.dumps({'scene':title,**row},ensure_ascii=False),flush=True)
        if '服务暂时无法响应' in answer or not answer:
            raise RuntimeError('primary_model_failed')
    report['scenes'].append({'title':title,'turns':rows})
    (OUT/'daily-chat-samples.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'completed':report['model_calls'],'model':provider.model_name,'selected':selected,
                  'persona':persona,'official_expression_rules':official},ensure_ascii=False),flush=True)
