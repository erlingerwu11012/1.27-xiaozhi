"""Persisted software device. Replies are derived from state transitions."""
import copy,json,tempfile,uuid
from pathlib import Path
from test_support import SimulationManager
from plugins_func.register import Action,ActionResponse
class StatefulDevice(SimulationManager):
    def __init__(self,path=None):
        super().__init__();self.path=Path(path or tempfile.gettempdir()+'/experience-device-'+uuid.uuid4().hex+'.json')
        self.state=json.loads(self.path.read_text()) if self.path.exists() else {'volume':50,'level':3,'alarms':[],'notes':[],'habits':[],'card':{'active':True,'instance_id':'sim-card','revision':2,'title':'拿快递','source_type':'note','status':'presenting','primary_action':'完成','secondary_action':'稍后提醒','tertiary_action':'这次不用了'},'broadcast':False,'render':{},'behavior':[]}
        d=self.tools['self_screen_set_brightness'].description['function'];d['description']='设置屏幕亮度档位，1 到 5；兼容50到100百分比，6到49无效。';d['parameters']['properties']['brightness'].update(minimum=1,maximum=100)
        self.state.setdefault('alarm_ringing',True);self.state.setdefault('enrollment',{'state':'capturing','accepted_count':1,'required_frames':3});self.state.setdefault('reboot_requested',False)
        self.save()
    def save(self):
        self.path.write_text(json.dumps(self.state,ensure_ascii=False))
        self.volume=self.state['volume'];self.brightness=self.state['level']
    async def _execute_tool(self,name,args):
        if name in self.faults:return await super()._execute_tool(name,args)
        self.calls.append({'tool':name,'arguments':copy.deepcopy(args)})
        body=None
        if name=='self_get_device_status':body={'audio_speaker':{'output_volume':self.state['volume']},'screen':{'brightness':self.state['level'],'brightness_level':self.state['level']}}
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
        elif name=='alarm_list':body='暂无闹钟' if not self.state['alarms'] else '\n'.join(f"[{i+1}] {a['hour']:02d}:{a['minute']:02d} {a['label']}" for i,a in enumerate(self.state['alarms']))
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
        elif name=='reminder_get_current':body=copy.deepcopy(self.state['card'])
        elif name=='reminder_list_pending':body={'items':[copy.deepcopy(self.state['card'])] if self.state['card'].get('active') else []}
        elif name=='reminder_action':
            card=self.state['card'];action=args['action']
            if not card.get('active') or args['instance_id']!=card.get('instance_id') or args['revision']!=card.get('revision'):body={'ok':False,'errorCode':'stale_revision','message':'卡片已更新'}
            else:
                card['revision']+=1;card['last_action']=action
                if action in {'primary','tertiary','cancel'}:card['active']=False
                if action=='secondary':card['status']='snoozed'
                body={'ok':True,'status':'completed','instance_id':card['instance_id'],'action':action,'revision':card['revision']}
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
