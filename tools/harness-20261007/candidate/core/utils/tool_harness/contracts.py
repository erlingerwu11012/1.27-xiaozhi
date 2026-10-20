"""Audited receipts. Unknown write tools fail closed, never guess from prose."""
import json,re
from dataclasses import dataclass
from .models import StepResult

READS={
 'get_lunar','get_world_time','memory_search','random_decision','habit_list_manual',
 'self_get_device_status','alarm_list','note_list','habit_list','reminder_get_current',
 'reminder_list_pending','self_camera_take_photo','self_camera_identify_person',
 'self_screen_get_render_status','self_get_system_info','self_screen_get_info','camera_face_enroll_status',
 'get_weather','get_news_from_newsnow',
}
WRITES={
 'handle_exit_intent','memory_correct','memory_forget','habit_create','add_reminder',
 'self_audio_speaker_set_volume','self_screen_set_brightness','alarm_set','alarm_delete',
 'alarm_dismiss','alarm_snooze','note_add','note_snooze','note_delete','reminder_begin_broadcast',
 'reminder_next','reminder_stop_broadcast','reminder_action','self_screen_set_render_mode',
 'self_screen_set_render_options','self_reboot','habit_learn','habit_delete','habit_confirm',
 'habit_reject','behavior_log','camera_face_enroll_start','camera_face_enroll_cancel',
}
LABELS={'self_audio_speaker_set_volume':'音量','self_screen_set_brightness':'亮度','alarm_set':'闹钟',
 'add_reminder':'提醒','note_add':'便签','memory_forget':'记忆删除','memory_correct':'记忆更正',
 'self_reboot':'设备重启','camera_face_enroll_start':'人脸采集','camera_face_enroll_cancel':'取消人脸采集'}
LABELS.update(dict(zip(['alarm_delete','alarm_dismiss','alarm_snooze','note_delete','note_snooze','habit_learn','habit_delete','habit_confirm','habit_reject','behavior_log','reminder_action','reminder_begin_broadcast','reminder_next','reminder_stop_broadcast','self_screen_set_render_mode','self_screen_set_render_options'],['删除闹钟','停止闹钟','闹钟稍后响铃','删除便签','推迟便签','保存习惯','删除习惯','确认习惯','跳过本次习惯','行为日志','卡片操作','开始播报','切换待办','停止播报','渲染模式','渲染配置'])))
PREREQUISITES={'alarm_delete':['alarm_list'],'note_delete':['note_list'],'note_snooze':['note_list'],
 'habit_delete':['habit_list'],'habit_confirm':['habit_list'],'habit_reject':['habit_list'],'reminder_action':['reminder_get_current'],
 'memory_forget':['memory_search'],'memory_correct':['memory_search']}
PATTERNS={
 'alarm_delete':r'已删除','habit_delete':r'已删除',
 'alarm_dismiss':r'\[ALARM_DISMISSED\]', 'alarm_snooze':r'\[ALARM_SNOOZED\] \d+',
 'note_snooze':r'\[NOTE_SNOOZED\] \d+', 'note_delete':r'\[NOTE_DELETED\]',
 'habit_confirm':r'\[HABIT_CONFIRMED\] .+', 'habit_reject':r'\[HABIT_SKIPPED_TODAY\] .+',
 'reminder_begin_broadcast':r'已开始逐项播报待办','reminder_next':r'已切换到下一项，当前事项仍会保留',
 'reminder_stop_broadcast':r'已停止播报，未处理待办会保留',
}

@dataclass(frozen=True)
class Contract:
    name:str
    write:bool
    known:bool
    prerequisites:tuple=()
    timeout:float=60
    retry:str='never-after-dispatch'

def contract(name):
    return Contract(name,name not in READS,name in READS|WRITES,tuple(PREREQUISITES.get(name,())))

def unpack(result):
    raw=getattr(result,'result',None)
    if raw is None:raw=getattr(result,'response',None)
    if isinstance(raw,str):
        try:return json.loads(raw)
        except ValueError:return raw.strip()
    return raw

def receipt(name,args,result,call_id):
    body=unpack(result);label=LABELS.get(name,name)
    def out(state,reply,error=''):return StepResult(state=state,tool=name,call_id=call_id,arguments=args,reply=reply,payload=body,error=error)
    action=getattr(getattr(result,'action',None),'name','')
    from core.utils.tool_result import MESSAGES
    code=body.get('errorCode') if isinstance(body,dict) else None
    if code in {'request_timeout','connection_closed','session_cancelled'}:
        return out('unknown',f'{label}完成结果尚未确认：{MESSAGES[code]}',code)
    if isinstance(body,str) and body==MESSAGES['request_timeout']:
        return out('unknown',body,'request_timeout')
    if action in {'ERROR','NOTFOUND'}:return out('unknown' if '超时' in str(body) else 'failed',f'{label}没有完成。','executor_error')
    if isinstance(body,str) and re.match(r'未授权|身份未|无法确认身份|权限|错误|失败|不支持|无效|不存在|未找到|请先|请在|.*已满|.*空间不足',body):
        return out('failed',f'{label}没有完成：{body}。','rejected')
    if isinstance(body,dict) and (body.get('ok') is False or body.get('success') is False or body.get('status') in {'error','failed','identity_unknown','temporarily_unavailable','disabled'} or body.get('isError') is True):
        return out('failed',f'{label}没有完成：{body.get("error") or body.get("message") or "工具返回失败"}。',code if code in MESSAGES else 'device_failure')
    if isinstance(body,dict) and (body.get('accepted') is True or body.get('status') in {'accepted','queued','running','starting'} or body.get('state') in {'accepted','queued','running','starting'}):
        return out('accepted',f'{label}请求已接收，尚未确认完成。')
    if getattr(result,'operation_state',None)=='completed' and name=='add_reminder':return out('completed','提醒已设好。')
    if name in {'self_audio_speaker_set_volume','self_screen_set_brightness'}:
        key='volume' if 'volume' in name else 'brightness';value=body.get(key) if isinstance(body,dict) else None
        expected=args.get(key)
        level_mode=isinstance(body,dict) and type(body.get('brightness_level')) is int
        if level_mode and key=='brightness':
            expected=expected if 1<=expected<=5 else (1 if expected<65 else 2 if expected<75 else 3 if expected<85 else 4 if expected<95 else 5)
        if isinstance(body,dict) and body.get('ok') is True and type(value) is int and value==expected:
            return out('completed',f'{label}已调到{value}{"档" if level_mode else ""}。')
    elif name=='alarm_set':
        text=f"已设置 {args.get('hour',-1):02d}:{args.get('minute',-1):02d} {args.get('label','')} "
        rd=args.get('repeat_days');suffix={0:'仅一次',127:'每天',62:'工作日',65:'周末'}.get(rd,'自定义')
        if body==text+'['+suffix+']':return out('completed',f"{args['hour']:02d}点{args['minute']:02d}分的闹钟已设置。")
        if isinstance(body,dict) and body.get('ok') is True and body.get('persisted') is True and all(body.get(k)==args.get(k) for k in ('hour','minute','repeat_days')) and type(body.get('id')) is int:
            return out('completed',f"{args['hour']:02d}点{args['minute']:02d}分的闹钟已设置。")
    elif name=='note_add':
        from datetime import datetime
        from zoneinfo import ZoneInfo
        expected='已记录：'+args.get('text','')
        if args.get('remind_at',0)>0:
            stamp=datetime.fromtimestamp(args['remind_at'],ZoneInfo('Asia/Shanghai')).strftime('%m/%d %H:%M')
            expected+='，将于 '+stamp+' 提醒'
        if body==expected:return out('completed','便签已记下。')
    elif name in PATTERNS:
        valid=isinstance(body,str) and bool(re.fullmatch(PATTERNS[name],body))
        if name=='alarm_snooze':valid=body==f"[ALARM_SNOOZED] {args.get('minutes')}"
        if name=='note_snooze':valid=body==f"[NOTE_SNOOZED] {args.get('delay_minutes')}"
        if valid:
            friendly={'alarm_delete':'对应闹钟已删除。','habit_delete':'对应习惯已删除。','alarm_dismiss':'闹钟已停止。','alarm_snooze':f"闹钟将在{args.get('minutes')}分钟后再响。",'note_snooze':f"便签提醒已推迟{args.get('delay_minutes')}分钟。",'note_delete':'对应便签已删除。','habit_confirm':'本次习惯已确认完成。','habit_reject':'已跳过今天这次习惯，规则仍保留。'}
            return out('completed',friendly.get(name,body))
    elif name=='reminder_action':
        from core.utils.reminder_tool_contracts import reminder_action_completed
        if reminder_action_completed(args,body):return out('completed',str(body))
    elif name=='habit_learn':
        if body==f"已记录习惯：{args.get('description','')}，每天 {args.get('hour',-1):02d}:{args.get('minute',-1):02d} 前 {args.get('advance_minutes',2)} 分钟提醒":return out('completed','习惯规则已保存。')
    elif name in {'self_screen_set_render_mode','self_screen_set_render_options'}:
        if isinstance(body,dict) and body.get('ok') is True and body.get('requires_reboot') is True:
            if name.endswith('mode') and body.get('next_boot_mode')!=args.get('mode'):return out('unknown','未确认配置保存。','mismatched_receipt')
            if name.endswith('options') and any(body.get('next_boot_'+k)!=args.get(k) for k in ('profile','spi_mhz','pixel_diff')):return out('unknown','未确认配置保存。','mismatched_receipt')
            return out('completed','配置已保存，重启后生效；本次没有重启设备。')
    elif name=='self_reboot':
        if body is True:return out('accepted','设备已接受重启请求，尚未确认重启完成。')
    elif name=='handle_exit_intent':
        if body=='退出意图已处理':return out('completed','对话已结束。')
    elif name in {'memory_correct','memory_forget'}:
        if isinstance(body,dict) and body.get('ok') is True and body.get('operation')==('correct' if name.endswith('correct') else 'forget'):return out('completed','记忆更正已保存。' if name.endswith('correct') else '指定记忆已删除。')
    elif name=='behavior_log':
        if isinstance(body,str) and body.startswith('{'):
            return out('unknown','尚未确认日志保存。')
        if isinstance(body,dict) and body.get('intent')==args.get('intent') and body.get('outcome')==args.get('outcome','conversation'):return out('completed','行为日志已记录。')
    elif name=='camera_face_enroll_start':
        if isinstance(body,str) and body in {'ENROLL_STARTED','[FACE_ENROLL_STARTED]','人脸录入已开始'}:return out('accepted','人脸采集请求已接收，尚未完成录入。')
    elif name=='camera_face_enroll_cancel':
        if isinstance(body,str) and body in {'采集已取消','已取消人脸录入','人脸采集已取消','已停止人脸采集'}:return out('completed','人脸采集已取消。')
    elif name in READS:
        valid=False
        if name=='self_get_device_status':valid=isinstance(body,dict) and any(k in body for k in ('volume','audio_speaker','screen'))
        elif name=='self_screen_get_info':valid=isinstance(body,dict) and all(type(body.get(k)) is int and body[k]>0 for k in ('width','height'))
        elif name=='camera_face_enroll_status':valid=isinstance(body,dict) and isinstance(body.get('state'),str) and type(body.get('accepted_count')) is int
        elif name in {'reminder_get_current','reminder_list_pending'}:valid=isinstance(body,(dict,list)) and (isinstance(body,list) or any(k in body for k in ('instance_id','current','items','pending','status','active')))
        elif name=='self_camera_identify_person':valid=isinstance(body,dict) and body.get('status') in {'known','unknown','ambiguous','no_face','empty'}
        elif name in {'self_screen_get_render_status','self_get_system_info'}:valid=isinstance(body,dict) and bool(set(body)&{'board','chip','mac_address','mode','profile','running_profile','flash_size','heap','psram','platform'})
        elif name in {'alarm_list','note_list','habit_list'}:
            valid=isinstance(body,str) and bool(re.fullmatch(r'(?:暂无闹钟|暂无备忘录|暂无习惯规则|共\d+个闹钟，已显示在屏幕上。|共\d+个闹钟，屏幕显示前4个，完整列表[:：]\n(?:\[\d+\].*\n?)+|(?:\[?\d+[\]. ].*\n?)+)',body))
        elif name=='get_world_time':
            from core.utils.tool_fact_reply import world_time_reply
            valid=not world_time_reply(args,body).startswith(('时间查询结果不完整','时间查询结果有冲突'))
        elif name=='get_lunar':valid=isinstance(body,str) and any(k in body for k in ('农历','干支','阴历'))
        elif name=='memory_search':valid=isinstance(body,dict) and isinstance(body.get('text'),str) and body.get('status') in {'found','ok','not_found','suppressed'}
        elif name=='random_decision':
            valid=False
            if isinstance(body,str):
                mode=args.get('mode')
                if mode=='coin':valid=bool(re.fullmatch(r'🪙 抛硬币结果：(正面|反面)',body))
                elif mode=='dice':valid=bool(re.fullmatch(r'🎲 掷骰子结果：[1-6] 点',body))
                elif mode=='number':
                    m=re.fullmatch(r'🔢 随机数 \((-?\d+)-(-?\d+)\)：(-?\d+)',body)
                    valid=bool(m and int(m[1])==args.get('min_val',1) and int(m[2])==args.get('max_val',100) and int(m[1])<=int(m[3])<=int(m[2]))
                elif mode=='pick':valid=body in {'🤔 经过深思熟虑，我帮你选：'+x.strip() for x in args.get('options','').replace('，',',').split(',') if x.strip()}
        elif name=='self_camera_take_photo':valid=isinstance(body,str) and len(body)>=2 and not body.startswith(('错误','失败','error'))
        if valid:
            reply=json.dumps(body,ensure_ascii=False) if not isinstance(body,str) else body
            if name=='self_get_device_status':
                speaker=body.get('audio_speaker',{});screen=body.get('screen',{})
                volume=body.get('volume',speaker.get('output_volume'));brightness=body.get('brightness',screen.get('brightness'))
                reply=''.join([f'当前音量是{volume}。' if type(volume) is int else '',f'当前亮度是{brightness}。' if type(brightness) is int else '']) or '设备状态已读取。'
            elif name=='memory_search':reply=body['text'] or '未找到对应记忆。'
            elif name=='reminder_get_current':reply='当前没有提醒卡片。' if body.get('active') is False else '当前提醒：'+str(body.get('title') or body.get('status') or '已读取')+'。'
            elif name=='camera_face_enroll_status':reply=f"人脸采集状态是{body['state']}，已采集{body['accepted_count']}张。"
            elif name=='self_screen_get_info':reply=f"屏幕分辨率是{body['width']}乘{body['height']}。"
            elif name=='get_lunar':
                # The plugin returns a prompt wrapper; only its factual fields
                # belong in speech. No second model is used to rewrite it.
                lines=[line.strip() for line in body.splitlines() if line.strip()]
                facts=[line for line in lines if re.match(r'^(阳历|公历|农历日期|阴历|干支|生肖|节气|星期|今日节气)[:：]',line)]
                if '农历信息：' in lines:
                    position=lines.index('农历信息：')+1
                    if position<len(lines):facts.insert(0,'农历：'+lines[position])
                if facts:reply='；'.join(facts)+'。'
                elif body.startswith('根据以下信息'):return out('unknown','农历查询结果缺少可核对的日期字段。','lunar_fields_missing')
            return out('completed',reply)
    return out('unknown',f'尚未确认{label}的完成结果。','unverified_receipt')
