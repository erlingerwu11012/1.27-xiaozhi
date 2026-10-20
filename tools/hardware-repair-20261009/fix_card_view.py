from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8');s=s.replace("        return '当前提醒是：'+title.strip()+'。'", "        visible=body.get('active',item.get('active'))\n        return ('屏幕上正在显示提醒卡片，内容是：' if visible is True else '当前提醒是：')+title.strip()+'。'")
p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/reply_composer.py';s=p.read_text(encoding='utf-8');s=s.replace('识人未确认时，只说明尚未认出；','当前卡片结果active=true表示正在展示，active=false表示已经关闭展示；必须直接回答卡片是否关闭，不能说有活跃提醒却无法判断卡片展示。\n识人未确认时，只说明尚未认出；')
needle="    for r in results:\n        if r.tool!='self_get_device_status'";a=s.index(needle);s=s[:a]+'''    for r in results:
        if r.tool!='reminder_get_current' or r.state!='completed' or not isinstance(r.payload,dict):continue
        body=r.payload;item=body.get('current',body);active=body.get('active',item.get('active') if isinstance(item,dict) else None)
        if active is True and re.search(r'(?:没有|没|无法|不能|不清楚|不知道|不确定|只能).{0,20}(?:卡片|开关|展示|显示|状态)|(?:卡片|屏幕).{0,15}(?:已经关闭|已关闭|没在显示|不再显示|无法确认|不能确认|查不到)',text):return True
        if active is False and re.search(r'(?:卡片|屏幕).{0,15}(?:正在显示|还在显示|仍在显示|正显示)|(?:还在|在的)[，,。]',text) and not re.search(r'没有|不再|没在|不是',text):return True
''' +s[a:];p.write_text(s,encoding='utf-8')
p=R/'run_model.py';s=p.read_text(encoding='utf-8');s=s.replace("if not state['reboot_requested'] or re.search(r'重启(?:成功|完成|好了)',speech)","if not state['reboot_requested'] or unsafe(speech,[StepResult.model_validate(x) for x in results])") # actual line parenthesized handle below
s=s.replace("(not state['reboot_requested'] or re.search(r'重启(?:成功|完成|好了)',speech))", "(not state['reboot_requested'] or unsafe(speech,[StepResult.model_validate(x) for x in results]))")
s=s.replace("(re.search(r'录入(?:完成|成功|好了)',speech) or state['enrollment']['state']!='capturing')", "(unsafe(speech,[StepResult.model_validate(x) for x in results]) or state['enrollment']['state']!='capturing')")
p.write_text(s,encoding='utf-8')
