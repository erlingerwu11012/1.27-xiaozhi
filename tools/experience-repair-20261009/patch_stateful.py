from pathlib import Path
p=Path('tools/experience-repair-20261009/stateful_device.py');s=p.read_text(encoding='utf-8-sig')
s=s.replace("        self.save()\n    def save", "        self.state.setdefault('alarm_ringing',True);self.state.setdefault('enrollment',{'state':'capturing','accepted_count':1,'required_frames':3});self.state.setdefault('reboot_requested',False)\n        self.save()\n    def save",1)
s=s.replace("        elif name=='alarm_list':", "        elif name=='alarm_dismiss':self.state['alarm_ringing']=False;body='[ALARM_DISMISSED]'\n        elif name=='alarm_snooze':self.state['alarm_ringing']=False;self.state['alarm_snooze_minutes']=args['minutes'];body=f\"[ALARM_SNOOZED] {args['minutes']}\"\n        elif name=='alarm_list':",1)
s=s.replace("        if body is None:", """        elif name=='habit_learn':
            self.state['habits'].append(copy.deepcopy(args));body=f"已记录习惯：{args['description']}，每天 {args['hour']:02d}:{args['minute']:02d} 前 {args.get('advance_minutes',2)} 分钟提醒"
        elif name=='habit_list':body='暂无习惯规则' if not self.state['habits'] else '\\n'.join(f"{i+1}. {h['hour']:02d}:{h['minute']:02d} {h['description']} [auto] 置信度:100" for i,h in enumerate(self.state['habits']))
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
""",1)
p.write_text(s,encoding='utf-8')
