from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/memory_policy.py';s=p.read_text();needle="    if re.search(r'音量|声音|亮度|屏幕";insert="    # Describing one's own forgetfulness is not a command to erase stored facts.\n    if re.search(r'忘记了|忘了',q) and not re.search(r'请.*忘|帮我.*忘|替我.*忘|把.{0,40}(?:记忆|记录|那件事).{0,10}忘|忘.{0,10}(?:吧|掉|记忆|记录)',q):return 'read'\n"
s=s.replace(needle,insert+needle,1);p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text();s=s.replace("    if re.search(r'(?:查|搜|检索|回忆).{0,25}","    if re.search(r'查|搜|检索|找|什么|啥|记着|记得',q) and re.search(r'记忆|偏好|饮料|爱喝|爱吃',q):return q\n    if re.search(r'(?:查|搜|检索|回忆).{0,25}",1)
needle="        if quoted_note_request(query):return False\n        if re.search"
s=s.replace(needle,"        if quoted_note_request(query):return False\n        if re.search(r'(?:没有|没)(?:让|叫|要求)你',q) and not re.search(r'而是|是让你|现在帮我|现在给我',q):return True\n        if re.search",1);p.write_text(s,encoding='utf-8')
# Add precise ordinary-chat acceptance checks; preserve every original failed row.
p=R/'run_model.py';s=p.read_text();s=s.replace(" if n is None:\n  feedback=", " if n is None:\n  if not row.get('expected_clarify') and re.search(r'这次请求没有执行完|确认操作目标或参数|尚未确认任何新的修改',speech):errors.append('ordinary_chat_replaced_by_operation_error')\n  feedback=");p.write_text(s,encoding='utf-8')
