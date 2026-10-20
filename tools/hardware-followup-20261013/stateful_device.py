"""Persisted software device. Replies are derived from state transitions."""
import copy,json,tempfile,uuid
from pathlib import Path
from test_support import SimulationManager
from plugins_func.register import Action,ActionResponse
class StatefulDevice(SimulationManager):
    def __init__(self,path=None):
        super().__init__();self.path=Path(path or tempfile.gettempdir()+'/experience-device-'+uuid.uuid4().hex+'.json')
        for removed in ('self_get_system_info','self_reboot','self_screen_get_info','self_screen_set_render_mode','self_screen_set_render_options','self_screen_get_render_status'):self.tools.pop(removed,None)
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'volume':50,'level':3,'alarms':[],'notes':[],'habits':[],'card':{'active':True,'instance_id':'sim-card','revision':2,'title':'拿快递','source_type':'note','status':'presenting','primary_action':'完成','secondary_action':'稍后提醒','tertiary_action':'这次不用了'},'broadcast':False,'render':{},'behavior':[]}
        d=self.tools['self_screen_set_brightness'].description['function'];d['description']='设置屏幕亮度档位，1 到 5；兼容50到100百分比，6到49无效。';d['parameters']['properties']['brightness'].update(minimum=1,maximum=100)
        from core.providers.tools.base import ToolDefinition,ToolType
        from plugins_func.functions import person_memory
        from plugins_func.functions.get_weather import GET_WEATHER_FUNCTION_DESC
        from plugins_func.functions.get_news_from_newsnow import GET_NEWS_FROM_NEWSNOW_FUNCTION_DESC
        from plugins_func.register import all_function_registry
        for name in ('memory_search','memory_correct','memory_forget'):
            self.tools[name].description=copy.deepcopy(all_function_registry[name].description)
        if 'memory_add' in all_function_registry:self.tools['memory_add']=ToolDefinition(name='memory_add',description=copy.deepcopy(all_function_registry['memory_add'].description),tool_type=ToolType.SERVER_PLUGIN)
        for description in (GET_WEATHER_FUNCTION_DESC,GET_NEWS_FROM_NEWSNOW_FUNCTION_DESC):
            name=description['function']['name'];self.tools[name]=ToolDefinition(name=name,description=copy.deepcopy(description),tool_type=ToolType.SERVER_PLUGIN)
        d={'type':'function','function':{'name':'reminder_close_current','description':'只关闭当前卡片，不完成、不删除事项；先读取reminder_get_current获得ID和revision。','parameters':{'type':'object','properties':{'instance_id':{'type':'string'},'revision':{'type':'integer','minimum':1,'maximum':2147483647}},'required':['instance_id','revision'],'additionalProperties':False}}}
        self.tools['reminder_close_current']=ToolDefinition(name='reminder_close_current',description=d,tool_type=ToolType.DEVICE_MCP)
        self.state.setdefault('alarm_ringing',True);self.state.setdefault('enrollment',{'state':'capturing','accepted_count':1,'required_frames':3});self.state.setdefault('reboot_requested',False)
        self.save()
    def save(self):
        self.path.write_text(json.dumps(self.state,ensure_ascii=False))
        self.volume=self.state['volume'];self.brightness=self.state['level']
    async def _execute_tool(self,name,args):
        if name in self.faults:return await super()._execute_tool(name,args)
        self.calls.append({'tool':name,'arguments':copy.deepcopy(args)})
        body=None
        if name=='get_weather':body='您查询的位置是：'+args.get('location','广州')+'\n当前天气:晴，20摄氏度。'
        elif name=='get_news_from_newsnow':body='新闻标题：软件协议测试新闻\n内容：这是隔离新闻回执，用于验证查询流程。'
        elif name=='random_decision':
            mode=args['mode']
            body={'coin':'🪙 抛硬币结果：正面','dice':'🎲 掷骰子结果：4 点'}.get(mode)
            if mode=='number':body=f"🔢 随机数 ({args.get('min_val',1)}-{args.get('max_val',100)})：{args.get('min_val',1)}"
            if mode=='pick':body='🤔 经过深思熟虑，我帮你选：'+args['options'].replace('，',',').split(',')[0].strip()
        elif name=='get_world_time':
            from datetime import datetime
            from zoneinfo import ZoneInfo
            from test_support import PACK
            moment=datetime.fromisoformat(PACK['clock']).astimezone(ZoneInfo(args['timezone']))
            minutes=int(moment.utcoffset().total_seconds()//60);sign='+' if minutes>=0 else '-';minutes=abs(minutes)
            offset=f'{sign}{minutes//60}'+(f':{minutes%60:02d}' if minutes%60 else '')
            body='🌍 '+args['timezone']+' 当前时间：\n'+moment.strftime('%Y年%m月%d日 %H:%M:%S (%A)')+'\n时区：UTC'+offset
        elif name=='self_get_device_status':body={'audio_speaker':{'volume':self.state['volume']},'screen':{'brightness':self.state['level'],'brightness_level':self.state['level']}}
        elif name=='self_audio_speaker_set_volume':self.state['volume']=args['volume'];body={'ok':True,'volume':self.state['volume']}
        elif name=='self_screen_set_brightness':
            v=args['brightness']
            if not (1<=v<=5 or 50<=v<=100):body={'ok':False,'errorCode':'invalid_brightness','message':'亮度范围无效'}
            else:
                level=v if v<=5 else (1 if v<65 else 2 if v<75 else 3 if v<85 else 4 if v<95 else 5)
                self.state['level']=level;body={'ok':True,'brightness':level,'brightness_level':level,'duty_percent':[0,82,86,91,95,100][level]}
        elif name=='alarm_set':
            self.state['alarms'].append(copy.deepcopy(args));suffix={0:'仅一次',127:'每天',62:'工作日',65:'周末'}.get(args['repeat_days'],'自定义');body=f"已设置 {args['hour']:02d}:{args['minute']:02d} {args['label']} [{suffix}]"
        elif name=='alarm_dismiss':self.state['alarm_ringing']=False;body='[ALARM_DISMISSED]'
        elif name=='alarm_snooze':self.state['alarm_ringing']=False;self.state['alarm_snooze_minutes']=args['minutes'];body=f"[ALARM_SNOOZED] {args['minutes']}"
        elif name=='alarm_list_legacy':body='暂无闹钟' if not self.state['alarms'] else '\n'.join(f"[{i+1}] {a['hour']:02d}:{a['minute']:02d} {a['label']}" for i,a in enumerate(self.state['alarms']))
        elif name=='alarm_list':body={'ok':True,'items':[{'id':i+1,'enabled':True,'last_triggered_at':0,**a} for i,a in enumerate(self.state['alarms'])]}
        elif name=='self_camera_take_photo':body={'success':True,'response':'画面里是一只蓝色杯子，放在桌面上。'}
        elif name=='reminder_close_current':
            card=self.state['card']
            if not card.get('active') or args['instance_id']!=card['instance_id'] or args['revision']!=card['revision']:body={'ok':False,'errorCode':'stale_revision','message':'卡片已更新'}
            else:
                card['active']=False;card['last_action']='close';body={'ok':True,'closed':True,'business_unchanged':True,'instance_id':args['instance_id'],'revision':args['revision'],'current_revision':args['revision']+1};card['revision']+=1
        elif name=='alarm_delete':self.state['alarms'].pop(args['index']-1);body='已删除'
        elif name=='note_add':
            self.state['notes'].append(copy.deepcopy(args));body='已记录：'+args['text']
            if args.get('remind_at',0)>0:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                body+='，将于 '+datetime.fromtimestamp(args['remind_at'],ZoneInfo('Asia/Shanghai')).strftime('%m/%d %H:%M')+' 提醒'
        elif name=='note_list':body='暂无备忘录' if not self.state['notes'] else '\n'.join(f"[{i+1}] {n['text']}" for i,n in enumerate(self.state['notes']))
        elif name=='note_delete':self.state['notes'].pop(args['index']-1);body='[NOTE_DELETED]'
        elif name=='note_snooze':self.state['notes'][args['index']-1]['delay_minutes']=args['delay_minutes'];body=f"[NOTE_SNOOZED] {args['delay_minutes']}"
        elif name=='reminder_get_current':body=copy.deepcopy(self.state['card']) if self.state['card'].get('active') else {'active':False}
        elif name=='reminder_list_pending':
            items=[{'source_type':'note','title':n['text'],'content':n['text'],'remind_at':n['remind_at'],'recipient_person_id':n.get('recipient_person_id'),'status':'pending'} for n in self.state['notes'] if n.get('remind_at',0)>0]
            if self.state['card'].get('active'):items.append(copy.deepcopy(self.state['card']))
            body={'items':items}
        elif name=='reminder_action':
            card=self.state['card'];action=args['action']
            if not card.get('active') or args['instance_id']!=card.get('instance_id') or args['revision']!=card.get('revision'):body={'ok':False,'errorCode':'stale_revision','message':'卡片已更新'}
            else:
                card['revision']+=1;card['last_action']=action
                if action in {'primary','secondary','tertiary','cancel'}:card['active']=False
                if action=='secondary':card['status']='snoozed'
                body={'primary':'提醒已完成','secondary':f"{args.get('minutes',15)}分钟后再次提醒",'tertiary':'已跳过本次提醒','cancel':'提醒已永久删除','silence':'已停止声音，事项仍待处理'}[action]
        elif name in {'reminder_begin_broadcast','reminder_stop_broadcast','reminder_next'}:
            self.state['broadcast']=name!='reminder_stop_broadcast';body={'reminder_begin_broadcast':'已开始逐项播报待办','reminder_stop_broadcast':'已停止播报，未处理待办会保留','reminder_next':'已切换到下一项，当前事项仍会保留'}[name]
        elif name=='habit_learn':
            self.state['habits'].append(copy.deepcopy(args));body=f"已记录习惯：{args['description']}，每天 {args['hour']:02d}:{args['minute']:02d} 前 {args.get('advance_minutes',2)} 分钟提醒"
        elif name=='habit_list':body='暂无习惯规则' if not self.state['habits'] else '\n'.join(f"{i+1}. {h['hour']:02d}:{h['minute']:02d} {h['description']} [auto] 置信度:100" for i,h in enumerate(self.state['habits']))
        elif name=='habit_delete':self.state['habits'].pop(args['index']-1);body='已删除'
        elif name in {'habit_confirm','habit_reject'}:
            h=self.state['habits'][args['index']-1];h['last_action']=name;body=('[HABIT_CONFIRMED] ' if name=='habit_confirm' else '[HABIT_SKIPPED_TODAY] ')+h['description']
        elif name=='behavior_log':self.state['behavior'].append(copy.deepcopy(args));body=copy.deepcopy(args)
        elif name in {'self_screen_set_render_mode','self_screen_set_render_options'}:
            self.state['render'].update({'next_boot_'+k:v for k,v in args.items()});body={'ok':True,'requires_reboot':True,**self.state['render']}
        elif name=='self_screen_get_render_status':body={'mode':'spine','profile':'v1',**self.state['render']}
        elif name=='camera_face_enroll_start':self.state['enrollment']['state']='capturing';body='[FACE_ENROLL_STARTED]'
        elif name=='camera_face_enroll_cancel':self.state['enrollment']['state']='cancelled';body='采集已取消'
        elif name=='camera_face_enroll_status':body=copy.deepcopy(self.state['enrollment'])
        elif name=='self_reboot':self.state['reboot_requested']=True;body=True
        elif name=='handle_exit_intent':self.state['conversation_closed']=True;body='退出意图已处理'
        if body is None:

            self.calls.pop();return await super()._execute_tool(name,args)
        self.save();r=ActionResponse(Action.REQLLM,result=json.dumps(body,ensure_ascii=False) if not isinstance(body,str) else body)
        self.calls[-1]['receipt']=r.result;return r
