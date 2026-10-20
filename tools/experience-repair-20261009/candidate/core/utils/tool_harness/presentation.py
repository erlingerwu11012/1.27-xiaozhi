"""Human-facing views of verified results, separate from private raw payloads."""
import json,re
from datetime import datetime
from zoneinfo import ZoneInfo

def safe_speech(text):
    text=str(text or '').strip()
    text=re.sub(r'\[(?:smirks|apologetic|happy|sad|angry|neutral|laughs|sighs|excited|whispering)\]','',text,flags=re.I)
    if not re.search(r'[\w\u3400-\u9fff]',text):return ''
    if re.match(r"^[{]\s*['\"]|^\[\s*[{]",text):return '这次没有取得可确认的结果，请稍后再试。'
    if text.startswith(('{','[')):
        try:json.loads(text)
        except (ValueError,TypeError):pass
        else:return '已收到查询结果，但暂时无法准确整理内容。'
    if re.search(r'\b(?:self_[a-z_]+|reminder_(?:action|get_current|list_pending)|memory_(?:correct|forget|search))\b',text):
        return '这次操作没有完成，请稍后再试。'
    return re.sub(r'。{2,}','。',text).strip()

def memory_items(body):
    if not isinstance(body,dict):return []
    items=body.get('items')
    if not isinstance(items,list):
        text=body.get('text','')
        # Legacy plain facts remain compatible. Wrapped archives are not writable facts.
        items=[{'text':text,'source':body.get('source','legacy')}] if isinstance(text,str) and text and not re.search(r'\[来源:|\[来源：|verified_results|"tool_calls"',text) else []
    result=[];seen=set()
    for item in items:
        if not isinstance(item,dict):continue
        text=item.get('text')
        if not isinstance(text,str) or not text.strip() or text in seen:continue
        if re.search(r'\[来源[:：]|\[本轮可信|"tool_calls"|"catalog_version"',text):continue
        seen.add(text);result.append({**item,'text':text.strip()})
    return result

def memory_reply(body):
    items=memory_items(body)
    if not items:return '没有找到能够确认的相关记忆。'
    facts=[item['text'] for item in items[:3]]
    return '你之前提到：'+'；'.join(facts)+'。'

def reminder_reply(body,current=False):
    if current:
        if not isinstance(body,dict):return '当前提醒内容未能确认。'
        if body.get('active') is False:return '当前没有提醒卡片。'
        item=body.get('current',body)
        if not isinstance(item,dict):return '当前提醒内容未能确认。'
        title=item.get('title') or item.get('content')
        if not isinstance(title,str) or not title.strip():return '当前有提醒卡片，但这次没有权限读取具体内容。'
        return '当前提醒是：'+title.strip()+'。'
    items=body if isinstance(body,list) else body.get('items',body.get('pending',[]))
    if not isinstance(items,list):return '待办列表格式异常，暂时无法读取。'
    if not items:return '当前没有待处理的提醒。'
    statuses={'pending':'待提醒','scheduled':'待提醒','presenting':'正在提醒','presented':'正在提醒','snoozed':'稍后再提醒','completed':'已完成','dismissed':'已关闭','waiting':'待处理'}
    parts=[]
    for item in items[:5]:
        if not isinstance(item,dict):continue
        title=item.get('title') or item.get('content')
        if not isinstance(title,str) or not title.strip():continue
        stamp=item.get('due_at')
        when=''
        if type(stamp) is int and 946684800<=stamp<=4102444800:
            when=datetime.fromtimestamp(stamp,ZoneInfo('Asia/Shanghai')).strftime('%m月%d日%H点%M分')+'，'
        state=statuses.get(item.get('status'),'待处理')
        person=item.get('recipient_display_name')
        who=('提醒'+person+'，') if isinstance(person,str) and person and person!='所有人' else ''
        parts.append(who+when+title.strip()+'，'+state)
    if not parts:return '这次没有读取到可确认的提醒内容。'
    suffix=f'，其余{len(items)-len(parts)}项未展开' if len(items)>len(parts) else ''
    return f'有{len(items)}项提醒：'+'；'.join(parts)+suffix+'。'

def card_action_reply(args,body):
    if isinstance(body,str):return safe_speech(body)+'。' if not body.endswith(('。','！','？')) else safe_speech(body)
    return {'primary':'本次提醒已确认完成。','secondary':f"将在{args.get('minutes')}分钟后再提醒。" if args.get('minutes',0)>0 else '已设为稍后再提醒。','tertiary':'本次提醒已跳过，以后的提醒保留。','cancel':'这条提醒已永久删除。','silence':'提醒声音已停止，事项仍待处理。'}.get(args.get('action'),'卡片操作已完成。')


def structured_read_reply(name,body):
    if name=='self_camera_identify_person':
        status=body.get('status')
        if status=='known':
            display=body.get('display_name') or body.get('name')
            return ('识别到的是'+display+'。') if isinstance(display,str) and display else '已匹配到登记人员，但未返回姓名。'
        return {'unknown':'看到人脸了，但没有确认是谁。','ambiguous':'识别结果有歧义，这次没有确认身份。','no_face':'这次没有检测到人脸。','empty':'还没有可用于识别的人脸资料。'}.get(status,'这次没有确认身份。')
    if name=='self_get_system_info':
        parts=[]
        if isinstance(body.get('chip'),str):parts.append('芯片是'+body['chip'])
        if type(body.get('flash_size')) is int:parts.append('Flash容量为'+str(round(body['flash_size']/1048576,2))+'MB')
        if type(body.get('free_heap')) is int:parts.append('剩余内存为'+str(body['free_heap'])+'字节')
        return '，'.join(parts)+'。' if parts else None
    if name=='self_screen_get_render_status':
        parts=[]
        for key,label in [('mode','渲染模式'),('running_mode','当前渲染模式'),('profile','配置'),('running_profile','当前配置')]:
            value=body.get(key)
            if isinstance(value,str) and value:parts.append(label+'是'+value)
        return '，'.join(parts)+'。' if parts else None
    return None


def legacy_list_reply(body):
    lines=[]
    for line in str(body).splitlines():
        match=re.match(r'^\[?(\d+)[.\]]\s*(.+)',line.strip())
        if match:
            fact=re.sub(r'\s*\[(?:auto|manual)\].*$', '',match[2]).strip()
            lines.append('第'+match[1]+'项：'+fact)
    return '；'.join(lines)+'。' if lines else str(body)


def device_status_reply(body,query=''):
    if not isinstance(body,dict):return '这次没有取得可确认的设备状态。'
    speaker=body.get('audio_speaker',{});speaker=speaker if isinstance(speaker,dict) else {}
    screen=body.get('screen',{});screen=screen if isinstance(screen,dict) else {}
    volume=body.get('volume',speaker.get('output_volume'))
    brightness=body.get('brightness',screen.get('brightness'))
    level=screen.get('brightness_level',body.get('brightness_level'))
    # Only describe the requested aspect when it is explicit.
    positive='，'.join(x for x in re.split('[，,；;。]',str(query)) if not re.match(r'^(?:这次|先|现在)?(?:不要|别|不用|不改|不动|不调)',x.strip()))
    focus=positive if re.search('音量|声音|亮度|几档',positive) else str(query)
    audio=bool(re.search('音量|声音',focus));display=bool(re.search('亮度|几档',focus))
    all_fields=not (audio or display)
    parts=[]
    if (audio or all_fields) and type(volume) is int:parts.append(f'当前音量是{volume}。')
    if display or all_fields:
        if type(level) is int:parts.append(f'当前亮度是{level}档。')
        elif type(brightness) is int:parts.append(f'当前亮度是{brightness}。')
    return ''.join(parts) or '这次返回的状态未包含所查询的数值。'
