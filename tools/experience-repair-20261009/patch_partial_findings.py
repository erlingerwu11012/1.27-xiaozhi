from pathlib import Path
S=Path('tools/experience-repair-20261009');p=S/'candidate/core/utils/device_reminder.py';s=p.read_text(encoding='utf-8-sig').replace('import json\n','import json,re\n',1)
a=s.index('    dialogue = getattr(conn, "dialogue", None)',s.index('def get_recent_user_text'));b=s.index('\n\n\ndef _log_reminder',a)
s=s[:a]+'''    from core.utils.person_identity import current_turn
    actor=current_turn(conn)
    accepted=getattr(conn,'_person_inputs',{}).get(getattr(actor,'turn_id',''))
    if isinstance(accepted,str) and accepted.strip():return accepted.strip()
    messages=getattr(getattr(conn,'dialogue',None),'dialogue',[]) or []
    return next((m.content.strip() for m in reversed(messages) if getattr(m,'role',None)=='user' and isinstance(m.content,str) and m.content.strip()),'')


def explicit_plain_note(text):
    if not re.search('便签|备忘录',text):return False
    if re.search(r'(?:保存|记录|记(?:一)?条|记下|写(?:一)?条|加(?:一)?条|新建|存(?:个|条)?)(?:便签|备忘录)(?:内容)?[:：]',text):return True
    positive=re.sub(r'(?:不要|不用|无需|不必|别|不设|不设置|没有)(?:设置)?(?:定时|提醒时间|提醒)','',text)
    return not bool(re.search('提醒|叫我|到点|告诉我',positive))
'''+s[b:]
s=s.replace("        inferred_time = extract_time_expression(text, recent_user)","        if remind_at==0 and not remind_time_str and explicit_plain_note(recent_user):\n            return None\n        inferred_time = extract_time_expression(text, recent_user)",1)
s=s.replace('无法确认时按公共提醒处理','无法确认时必须询问接收人，不能自动改成公共提醒');p.write_text(s,encoding='utf-8')
p=S/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
s=s.replace("        quoted_note=bool(re.match(r'^(?:只)?(?:保存|记录)(?:便签|备忘录)[:：]',plain))", "        quoted_note=bool(re.search(r'(?:保存|记录|记(?:一)?条|记下|写(?:一)?条|加(?:一)?条|新建|存(?:个|条)?)(?:便签|备忘录)(?:内容)?[:：]',plain))")
s=s.replace("                targets=self.write_targets(query) if not prohibited else set()", "                targets=(self.write_targets(query)|set(adjustments)|set(constraints)) if not prohibited else set()",1)
s=s.replace("if write_scope is None:write_scope=set(decision.authorized_writes)|{s.tool for s in decision.steps if contract(s.tool).write}","if write_scope is None:write_scope=set(decision.authorized_writes)|targets|{s.tool for s in decision.steps if contract(s.tool).write}",1)
s=s.replace("                    if s.tool in adjustments and (s.relative!=adjustments[s.tool] or s.extreme is not None):raise ValueError('relative_goal_requires_delta:'+str(adjustments[s.tool]))", "                    if s.tool in adjustments and (s.relative!=adjustments[s.tool] or s.extreme is not None):\n                        if s.relative is None and s.extreme is None and any(r.tool=='self_get_device_status' and r.state=='completed' for r in outcome.results):\n                            body=next(r.payload for r in reversed(outcome.results) if r.tool=='self_get_device_status' and r.state=='completed')\n                            key='volume' if 'volume' in s.tool else 'brightness';sub=body.get('audio_speaker' if key=='volume' else 'screen',{})\n                            value=body.get(key,sub.get('output_volume' if key=='volume' else 'brightness_level',sub.get(key)))\n                            from .domains import bounds\n                            lo,hi=bounds(s.tool,tools[s.tool]);delta=adjustments[s.tool]\n                            if key=='brightness' and (lo,hi)==(1,5) and abs(delta)==10:delta=1 if delta>0 else -1\n                            if type(value) is not int or s.arguments.get(key)!=max(lo,min(hi,value+delta)):raise ValueError('relative_goal_requires_verified_delta')\n                            s.relative=adjustments[s.tool]\n                        else:raise ValueError('relative_goal_requires_delta:'+str(adjustments[s.tool]))",1)
s=s.replace("最大|最小',clause):targets.add(name)","最大|最小|最高|最低|最亮|最暗',clause):targets.add(name)")
s=s.replace("('亮度','self_screen_set_brightness')", "('亮度|屏幕','self_screen_set_brightness')",1)
s=s.replace("            if request.kind=='note' and re.search('[，,；;]',q):return None", "            if request.kind=='note':return None",1)
s=s.replace('最大/最小用extreme=maximum/minimum。','最大/最小（最高/最低、最亮/最暗）用extreme=maximum/minimum，relative省略；例如“声音压到最低”直接设置minimum，不需要先查；“屏幕往下调一档”使用relative=-1，不自行填绝对档位。')
p.write_text(s,encoding='utf-8')
p=S/'candidate/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8');s+='''

def legacy_list_reply(body):
    lines=[]
    for line in str(body).splitlines():
        match=re.match(r'^\\[?(\\d+)[.\\]]\\s*(.+)',line.strip())
        if match:
            fact=re.sub(r'\\s*\\[(?:auto|manual)\\].*$', '',match[2]).strip()
            lines.append('第'+match[1]+'项：'+fact)
    return '；'.join(lines)+'。' if lines else str(body)
''';p.write_text(s,encoding='utf-8')
p=S/'candidate/core/utils/tool_harness/contracts.py';s=p.read_text(encoding='utf-8');s=s.replace("            elif name=='memory_search':", "            elif name in {'alarm_list','note_list','habit_list'}:\n                from .presentation import legacy_list_reply\n                reply=legacy_list_reply(body)\n            elif name=='memory_search':",1);p.write_text(s,encoding='utf-8')
p=S/'package_candidate.py';s=p.read_text(encoding='utf-8-sig').replace("names=['core/websocket_server.py'", "names=['core/utils/device_reminder.py','core/websocket_server.py'",1);p.write_text(s,encoding='utf-8')
