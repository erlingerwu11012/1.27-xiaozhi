"""Real production model; real Harness; isolated in-memory executors and ledger."""
import argparse
import asyncio
import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

parser=argparse.ArgumentParser()
parser.add_argument('--phase',choices=['baseline','candidate'],required=True)
parser.add_argument('--name',required=True)
parser.add_argument('--groups',default='chat,settings,memory')
args=parser.parse_args()
STAGE=Path('/root/prjs/tmp/dialogue-fix-20261017')
WORK=STAGE/args.phase
sys.path.insert(0,str(WORK))
os.environ['PERSON_MATERIAL_OUTBOX']=str(STAGE/(args.name+'-outbox.sqlite3'))
os.chdir(WORK)
logger=types.ModuleType('config.logger');logger.setup_logging=lambda:MagicMock()
sys.modules['config.logger']=logger
import config
config.logger=logger
from core.utils.person_identity import PersonTurn,activate,deactivate
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.utils.tool_harness.speech_output import SpeechOutput
from core.utils.dialogue import Dialogue,Message
from core.providers.tools.base import ToolType,ToolDefinition
from plugins_func.register import Action,ActionResponse,all_function_registry
import plugins_func.functions.person_memory
from core.providers.llm.openai.openai import LLMProvider

cfg=json.loads((STAGE/'private-model-config.json').read_text())
live=next(x for x in json.loads(subprocess.check_output(['pm2','jlist'])) if x['pm2_env']['status']=='online' and x['name']=='xiaozhi-server')
for field in (Path('/proc')/str(live['pid'])/'environ').read_bytes().split(b'\0'):
    k,sep,v=field.partition(b'=')
    if sep and k.decode() in {'HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN'}:
        os.environ[k.decode()]=v.decode()
provider=LLMProvider(copy.deepcopy(cfg['LLM'][cfg['selected_module']['LLM']]))
budget=STAGE/'model-call-count.json'

def cap(request):
    assert '/chat/completions' in request.url.path
    n=json.loads(budget.read_text())['calls'] if budget.exists() else 0
    if n>=110:raise RuntimeError('replay_model_request_limit')
    budget.write_text(json.dumps({'calls':n+1,'limit':110}))
provider.client._client.event_hooks['request'].append(cap)


def definition(name,properties,required,desc='',source=ToolType.DEVICE_MCP):
    return ToolDefinition(name,{'type':'function','function':{'name':name,'description':desc or name,
        'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}},source)


class Simulation:
    def __init__(self,conn):
        self.conn=conn;self.volume=40;self.brightness=4;self.facts={};self.calls=[];self.fail_memory=False;self.notes=[]
        self.tools={
            'self_get_device_status':definition('self_get_device_status',{},[],'读取设备当前音量和亮度'),
            'self_audio_speaker_set_volume':definition('self_audio_speaker_set_volume',{'volume':{'type':'integer','minimum':0,'maximum':100}},['volume'],'设置音量'),
            'self_screen_set_brightness':definition('self_screen_set_brightness',{'brightness':{'type':'integer','minimum':1,'maximum':100}},['brightness'],'设置屏幕亮度档位。brightness 取 1 到 5：1 是最暗，占空比 82%；5 是最亮，占空比 100%。调亮或调暗时，先调用 self.get_device_status 读取 screen.brightness_level，再对档位加减 1，并限制在 1-5。不要按百分比加减。兼容旧的 50-100 百分比：50-64 为 1 档，65-74 为 2 档，75-84 为 3 档，85-94 为 4 档，95-100 为 5 档。6-49 无效。'),
            'note_add':definition('note_add',{'text':{'type':'string'},'remind_at':{'type':'integer'}},['text'],'设备便签'),
        }
        from core.providers.tools.device_reminder_adapter import timed_note_definition
        self.tools['add_reminder']=timed_note_definition(conn,self.tools)
        self.tools['note_list']=definition('note_list',{},[],'查看所有备忘录，包含状态标注（待办/已提醒/已过期）。')
        self.tools['note_delete']=definition('note_delete',{'index':{'type':'integer','minimum':1,'maximum':20}},['index'],'删除指定序号的备忘录（从1开始，最新的排第1）。')

        for name in ['memory_add','memory_search','memory_correct','memory_forget']:
            self.tools[name]=ToolDefinition(name,copy.deepcopy(all_function_registry[name].description),ToolType.SERVER_PLUGIN)
    def refresh_tools(self):pass
    def get_all_tools(self):return self.tools
    def get_ambiguous_tool_names(self):return set()
    async def _execute_tool(self,name,arguments):
        self.calls.append({'tool':name,'arguments':arguments})
        if name=='self_get_device_status':body={'audio_speaker':{'volume':self.volume},'screen':{'brightness':self.brightness,'brightness_level':self.brightness}}
        elif name=='self_audio_speaker_set_volume':
            self.volume=arguments['volume'];body={'ok':True,'volume':self.volume}
        elif name=='self_screen_set_brightness':
            self.brightness=arguments['brightness'];body={'ok':True,'brightness':self.brightness,'brightness_level':self.brightness}
        elif name=='memory_add':
            if self.fail_memory:return ActionResponse(Action.ERROR,result='synthetic_executor_error')
            fact=arguments['fact'];rid='material:'+str(len(self.facts)+1);version=hashlib.sha256(fact.encode()).hexdigest()
            self.facts[rid]={'record_id':rid,'text':fact,'version':version,'source':'explicit_fact'}
            body={'ok':True,'local_applied':True,'operation':'add','fact':fact,'record_id':rid,'version':version,'cloud_sync':'disabled'}
        elif name=='memory_correct':
            rid=arguments.get('record_id')
            if rid not in self.facts:return ActionResponse(Action.ERROR,result='synthetic_missing_record')
            value=arguments['replacement'];version=hashlib.sha256(value.encode()).hexdigest()
            self.facts[rid]={'record_id':rid,'text':value,'version':version,'source':'local_override'}
            body={'ok':True,'local_applied':True,'operation':'correct','replacement':value,'resolved_match':arguments.get('match',''),'record_id':rid,'version':version,'cloud_sync':'disabled'}
        elif name=='note_list':body=''.join(str(i+1)+'. '+x+' [待办]\n' for i,x in enumerate(self.notes)) or '暂无备忘录'
        elif name=='note_delete':
            index=arguments['index']-1
            if not 0<=index<len(self.notes):return ActionResponse(Action.ERROR,result='synthetic_invalid_index')
            self.notes.pop(index);body='[NOTE_DELETED]'
        elif name=='memory_search':
            rows=list(self.facts.values())
            if arguments.get('record_ids'):rows=[r for r in rows if r['record_id'] in arguments['record_ids']]
            body={'status':'ok' if rows else 'not_found','items':rows,'text':'；'.join(r['text'] for r in rows),'scope':arguments.get('scope','related'),'source':'local','total_complete':False}
        elif name=='add_reminder':
            self.notes.insert(0,'吃饭')
            # Only simulate a correlated persisted result. Never call the device,
            # reminder API, production MySQL, or real memory writer.
            result=ActionResponse(Action.REQLLM,result={'ok':True,'persisted':True,'remind_at':int(time.time())+120,'recipient_person_id':'experience-person'})
            result.operation_state='completed';return result
        else:return ActionResponse(Action.ERROR,result='simulation_unsupported')
        return ActionResponse(Action.REQLLM,result=body)


GROUPS={
 'feedback':['哎，怎么不说话了？','你好，小贱'],
 'chat':['晚上好，你在干什么？','哎，今天稍微有点烦呢','不是我Cloud没法儿上传到电脑上，我好烦','不是，是这个cloud code，它说我被隔离了，什么上传不了','我也不清楚啊','这我还真不知道嘞','哎，怎么不说话了？','搞心态咋办呢你会办吗？','你好，小贱','哎呀，你听错了，我叫你小念'],
 'memory':['你记一下，我的老婆叫秦蕊，秦朝的秦，花蕊的蕊','我老婆叫啥名儿啊','那我老婆叫啥呀','你改一下，我老婆现在不叫秦蕊了，叫秦章，弓长张','你再改一下，你张字打错了，是弓长张','那我老婆叫啥呀'],
 'settings':['哎呀，你的声音有点太小了，小聂','再调大声一点呗','屏幕也有点暗了，我都看不清你了，再大再亮一点','你调了呗调到最亮了','把亮度调到最大'],
 'reminders':['五分钟后提醒我吃饭','我现在有什么提醒啊？','呃，我不吃了，你把这饼删了吧','我现在有什么提醒啊？'],
}

def validate(group,index,query,result,calls):
    errors=[]
    if result.error:errors.append('harness:'+result.error)
    if not result.reply:errors.append('empty_reply')
    if group=='memory':
        expected={0:'memory_add',1:'memory_search',2:'memory_search',5:'memory_search'}.get(index)
        if expected and not any(x.tool==expected and x.state=='completed' for x in result.results):errors.append('missing_success:'+expected)
        if index in [1,2] and '秦蕊' not in result.reply:errors.append('lost_saved_name')
        if index==3 and any(x.tool=='memory_correct' and x.state=='completed' and '章' in x.arguments.get('replacement','').split('，')[0] for x in result.results):errors.append('wrong_character_written')
        if index==5 and '秦张' not in result.reply:errors.append('lost_corrected_name')
    if group=='reminders' and index==2 and not any(x.tool=='note_delete' and x.state=='completed' for x in result.results):errors.append('reminder_not_deleted')
    if group=='settings' and index==4 and not any(x.tool=='self_screen_set_brightness' and x.state=='completed' and x.arguments.get('brightness')==5 for x in result.results):errors.append('not_max_brightness')
    return errors


async def run():
    import core.utils.prompt_manager as pm
    pm.V2_PLATFORM_TEMPLATE_PATH=str(WORK/'agent-base-prompt-v2.txt')
    system=pm.PromptManager(cfg,MagicMock()).build_enhanced_prompt_v2(cfg.get('prompt',''),'EXPERIENCE-NO-HARDWARE',None,device_name=cfg.get('device_custom_name','小念'),official_enhanced=True)
    report=STAGE/(args.name+'.jsonl')
    assert not report.exists(),'do not overwrite replay evidence'
    for group in args.groups.split(','):
        conn=SimpleNamespace(config={'harness':{'enabled':True}},device_id='EXPERIENCE-NO-HARDWARE',session_id='replay-'+group,
            _harness_request_generation=0,account_id='experience-account',_person_inputs={},harness_test_clock='2026-10-17T19:24:00+08:00',llm=provider)
        conn.mcp_client=SimpleNamespace(ready=True,closed=False,catalog_version=1,name_mapping={},has_tool=lambda n:n in {'note_add','note.add'})
        manager=Simulation(conn);conn.func_handler=SimpleNamespace(tool_manager=manager)
        conn.dialogue=Dialogue();conn.dialogue.update_system_message(system)
        ledger=Ledger(':memory:');harness=Harness(conn,ledger=ledger)
        history=[{'role':'system','content':system}]
        for index,query in enumerate(GROUPS[group]):
            actor=PersonTurn('experience-account','experience-person',0,1,'personal','matched',group+'-'+str(index),conn.device_id,'experience-agent',index,captured_at=int(time.time()*1000))
            conn.person_turn=actor;conn._person_inputs[actor.turn_id]=query;conn._harness_request_generation+=1

            token=activate(conn,actor)
            msg=Message(role='user',content=query);msg.material_actor_key=actor.key;conn.dialogue.put(msg)
            history.append({'role':'user','content':query})
            start=time.monotonic();start_calls=len(manager.calls);events=[];observed=[]
            output=SpeechOutput(lambda:True,lambda:events.append(('begin',time.monotonic())),lambda t:events.append(('text',time.monotonic(),t)),lambda:events.append(('end',time.monotonic())))
            harness.observe=lambda event,**kw:observed.append({'event':event,**kw})
            try:
                result=await harness.run(query,[history[0]]+history[1:][-16:],speech_output=output)
                spoken=output.finish(result.reply)
                if spoken!=result.reply:result.reply=spoken
            finally:deactivate(token)
            elapsed=round((time.monotonic()-start)*1000,1)
            history.append({'role':'assistant','content':result.reply});conn.dialogue.put(Message(role='assistant',content=result.reply))
            calls=manager.calls[start_calls:]
            usage=[x for x in observed if x['event']=='model_usage']
            row={'phase':args.phase,'group':group,'index':index,'query':query,'reply':result.reply,
                 'elapsed_ms':elapsed,'first_text_ms':round((output.first_text_at-start)*1000,1) if output.first_text_at else None,
                 'model_calls':result.model_calls,'results':[{'tool':r.tool,'state':r.state} for r in result.results],
                 'errors':validate(group,index,query,result,calls),'calls':calls,'usage':usage,
                 'state':{'volume':manager.volume,'brightness':manager.brightness,'facts':list(manager.facts.values()),'notes':list(manager.notes)}}
            with report.open('a') as f:f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
            print(json.dumps({k:row[k] for k in ['group','index','query','reply','first_text_ms','model_calls','errors']},ensure_ascii=False),flush=True)
        ledger.close()


asyncio.run(run())
