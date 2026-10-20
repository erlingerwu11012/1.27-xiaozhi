import asyncio,copy,json,types
from pathlib import Path
from bootstrap import stage
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.providers.tools.base import ToolDefinition,ToolType
from plugins_func.register import Action,ActionResponse

PACK=json.loads((stage/'pack.json').read_text())
def definitions():
    return {x['function']['name']:ToolDefinition(x['function']['name'],{k:copy.deepcopy(v) for k,v in x.items() if k!='source'},ToolType(x['source'])) for x in PACK['tools']}

class SimulationManager:
    def __init__(self):
        self.tools=definitions();self.calls=[];self.faults={};self.volume=50;self.brightness=80
        self.conn=None
    def refresh_tools(self):pass
    def get_all_tools(self):return self.tools
    def get_ambiguous_tool_names(self):return set()
    async def _execute_tool(self,name,args):
        self.calls.append({'tool':name,'arguments':copy.deepcopy(args)})
        if name in self.faults:
            fault=self.faults[name]
            if isinstance(fault,Exception):raise fault
            if callable(fault):return await fault(name,args)
            return fault
        body=copy.deepcopy(PACK['fixtures'][name]['receipt'])
        if name=='self_get_device_status':body={'audio_speaker':{'output_volume':self.volume},'screen':{'brightness':self.brightness}}
        elif name=='self_audio_speaker_set_volume':self.volume=args['volume'];body={'ok':True,'volume':self.volume}
        elif name=='self_screen_set_brightness':self.brightness=args['brightness'];body={'ok':True,'brightness':self.brightness}
        elif name=='alarm_set':
            suffix={0:'仅一次',127:'每天',62:'工作日',65:'周末'}.get(args['repeat_days'],'自定义')
            body=f"已设置 {args['hour']:02d}:{args['minute']:02d} {args['label']} [{suffix}]"
        elif name=='note_add':
            body='已记录：'+args['text']
            if args.get('remind_at',0)>0:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                body+='，将于 '+datetime.fromtimestamp(args['remind_at'],ZoneInfo('Asia/Shanghai')).strftime('%m/%d %H:%M')+' 提醒'
        elif name=='alarm_list':body='共1个闹钟，已显示在屏幕上。'
        elif name=='note_list':body='1. 买牛奶 [待办]'
        elif name=='habit_list':body='1. 08:00 喝水 [auto] 置信度:100'
        elif name=='reminder_list_pending':body={'items':[{'instance_id':'sim-card','revision':2,'title':'喝水','status':'presented'}]}
        elif name=='reminder_action':
            # Mirror the firmware action-specific legacy receipt. The previous
            # simulator incorrectly returned the primary receipt for silence.
            from core.utils.reminder_tool_contracts import ACTION_RECEIPTS
            if args.get('action')=='secondary' and args.get('minutes',0)>0:body=f"{args['minutes']}分钟后再次提醒"
            else:body=ACTION_RECEIPTS.get(args.get('action'),('unsupported reminder action',))[0]
        elif name=='memory_search' and '咖啡' in args.get('query',''):body={'status':'found','text':'喜欢咖啡','source':'local'}
        elif name=='self_screen_set_render_options':body={'ok':True,'requires_reboot':True,**{'next_boot_'+k:v for k,v in args.items()}}
        elif name=='behavior_log':body=copy.deepcopy(args)
        elif name=='habit_learn':body=f"已记录习惯：{args['description']}，每天 {args['hour']:02d}:{args['minute']:02d} 前 {args.get('advance_minutes',2)} 分钟提醒"
        elif name=='alarm_snooze':body=f"[ALARM_SNOOZED] {args['minutes']}"
        elif name=='note_snooze':body=f"[NOTE_SNOOZED] {args['delay_minutes']}"
        result=ActionResponse(Action.REQLLM,result=body if isinstance(body,str) else json.dumps(body,ensure_ascii=False))
        self.calls[-1]['receipt']=result.result
        if name=='add_reminder':result.operation_state='completed'
        return result
    async def execute_tool(self,name,args):return await self._execute_tool(name,args)

def connection(manager=None,decide=None):
    manager=manager or SimulationManager()
    conn=types.SimpleNamespace(device_id='SIMULATION-NO-HARDWARE',session_id='sim-session',listen_epoch=1,person_turn=None,func_handler=types.SimpleNamespace(tool_manager=manager),harness_test_clock=PACK['clock'],config={})
    manager.conn=conn
    h=Harness(conn,ledger=Ledger(':memory:'),decide=decide or (lambda _:None))
    return conn,manager,h

def step(name,args=None,**extra):return {'id':'a','tool':name,'arguments':args or {},**extra}
def decision(*steps,mode='operate',**extra):return {'mode':mode,'reply':'','goal':'用户请求','steps':list(steps),**extra}

def argument_matches(key,actual,expected):
    if key=='content' and actual==f'该{expected}了':return True
    if key=='remind_time_str':
        from datetime import datetime
        from core.utils.remind_time import parse_remind_time
        clock=datetime.fromisoformat(PACK['clock'])
        a=parse_remind_time(str(actual or ''),now=clock)
        e=parse_remind_time(str(expected or ''),now=clock)
        return a is not None and e is not None and a.remind_at==e.remind_at
    return actual==expected

def effective_arguments(tool,args):
    args=dict(args)
    if tool=='add_reminder' and isinstance(args.get('text'),str) and not args.get('content'):
        from core.utils.device_reminder import _split_content_and_time
        body,when=_split_content_and_time(args['text'],'','')
        args.update(content=body,remind_time_str=when)
    return args


def check(row,outcome,calls):
    if row['group']=='negative':return not calls and outcome.mode in {'chat','clarify'}
    relevant=[r for r in outcome.results if r.tool==row['tool']]
    if len(relevant)!=1:return False
    wanted='accepted' if row['tool'] in {'self_reboot','camera_face_enroll_start','memory_forget','memory_correct'} else 'completed'
    if relevant[0].state!=wanted:return False
    args=effective_arguments(row['tool'],relevant[0].arguments)
    for k,v in row['arguments'].items():
        if k in {'say_goodbye','query','question'}:
            if not isinstance(args.get(k),str) or not args[k]:return False
        elif k=='label' and row['tool']=='alarm_set':
            if not isinstance(args.get(k),str) or not args[k]:return False
        elif k=='remind_time_str':
            from core.utils.remind_time import cn_num_to_int
            import re
            def normalized(t):return re.sub(r'[零〇一二两三四五六七八九十百]+',lambda m:str(cn_num_to_int(m[0])),str(t))
            if normalized(args.get(k))!=normalized(v):return False
        elif not argument_matches(k,args.get(k),v):return False
    allowed={row['tool']}
    from core.utils.tool_harness.contracts import contract
    allowed.update(contract(row['tool']).prerequisites)
    if row['tool'] in {'self_audio_speaker_set_volume','self_screen_set_brightness'}:allowed.add('self_get_device_status')
    return all(c['tool'] in allowed for c in calls)
