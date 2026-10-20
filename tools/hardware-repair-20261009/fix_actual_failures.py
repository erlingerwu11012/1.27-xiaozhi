from pathlib import Path
import json
R=Path('tools/hardware-repair-20261009');W=R/'work'
p=W/'core/utils/tool_harness/memory_policy.py';s=p.read_text();s=s.replace("r'音量|亮度|屏幕", "r'音量|声音|亮度|屏幕");p.write_text(s,encoding='utf-8')
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text()
s=s.replace("direction=re.search(r'(?:调|提|降|升|变|开|放|增|减|加).{0,8}?(大|小|高|低|亮|暗)',clause)","direction=re.search(r'(?:调|提|降|升|变|开|放|增|减|加).{0,8}?(大|小|高|低|亮|暗)',clause) or re.search(r'(?:往|向)(上|下)(?:调|加|减|升|降)',clause)")
s=s.replace("direction[1] in {'大','高','亮'}", "direction[1] in {'大','高','亮','上'}")
s=s.replace("提高|降低|最大|最小|最高|最低|最亮|最暗',clause)","提高|降低|往上加|往下减|向上调|向下调|最大|最小|最高|最低|最亮|最暗',clause)")
s=s.replace("'write_goal_requires_write_steps':'这次只完成了前面的查询，设置操作没有执行。'", "'write_goal_requires_write_steps':('这次只完成了查询，设置操作没有执行。' if outcome.results else '这次设置没有执行，状态没有改变。')")
# All ambiguous clock hours require specific clarification, including weekday alarms.
needle="        adjustments={} if quoted_note else relative_requirements(query)"
insert='''        if not prohibited and not quoted_note and re.search(r'闹钟|习惯|提醒',plain) and re.search(r'设|定|创建|保存|新增|提醒我',plain) and not re.search(r'查|列表|哪些|什么|删除|取消|早|晨|上午|中午|下午|晚上|夜|凌晨|傍晚',plain):
            from core.utils.remind_time import cn_num_to_int
            hour_match=re.search(r'([零〇一二两三四五六七八九十百\\d]+)[点时]',plain)
            hour=cn_num_to_int(hour_match[1]) if hour_match else None
            if hour is not None and 1<=hour<=12:
                outcome.mode='clarify';outcome.reply=f'你说的{hour}点，是上午还是下午？'
                self.pending=(scope,time.monotonic(),{'user':query,'question':outcome.reply,'goal':'确认上午或下午'});return outcome
'''
s=s.replace(needle,insert+needle);p.write_text(s,encoding='utf-8')
p=W/'core/utils/recipient_resolver.py';s=p.read_text(encoding='utf-8-sig');s=s.replace('    raw = (text or "").strip()\n    if not raw:', '    raw = (text or "").strip()\n    # Remove only leading polite scaffolding, retaining the actual recipient.\n    raw = re.sub(r"^(?:(?:请|麻烦|可以|能不能|帮我|替我)\\s*)+(?=给|帮)", "", raw)\n    if not raw:',1);p.write_text(s,encoding='utf-8')
p=W/'core/utils/unified_recipient_resolver.py';s=p.read_text();s=s.replace('message="未找到该统一用户，请在用户管理页面检查 user_id。",','message="未找到该统一用户，请在用户管理页面检查 user_id。",\n            error_code="recipient_not_found",');s=s.replace('message="未找到该用户，请先在用户管理中创建并绑定身份。",','message="未找到该用户，请先在用户管理中创建并绑定身份。",\n        error_code="recipient_not_found",');p.write_text(s,encoding='utf-8')
p=W/'core/utils/tool_result.py';s=p.read_text();s=s.replace("    'not_found':", "    'recipient_not_found': '没有找到指定的接收人，请确认账号中登记的姓名。',\n    'not_found':");p.write_text(s,encoding='utf-8')
p=W/'core/utils/tool_harness/reply_composer.py';s=p.read_text();needle="    completion=r'";insert='''    # A read receipt never authorizes claims that a setting was changed.
    for tool,noun in [('self_audio_speaker_set_volume','音量|声音'),('self_screen_set_brightness','亮度|屏幕')]:
        if any(r.tool==tool and r.state=='completed' for r in results):continue
        for clause in re.split('[，,。；;]',text):
            if re.search(r'没有|未能|尚未|没能|不能|无法|还没|未完成|无需重复',clause):continue
            if re.search(r'(?:'+noun+r').{0,10}(?:已|已经).{0,10}(?:调|设)|(?:已|已经|帮你|替你).{0,8}(?:'+noun+r').{0,10}(?:调|设)|(?:'+noun+r').{0,8}(?:调好|设好)',clause):return True
'''
s=s.replace(needle,insert+needle,1);p.write_text(s,encoding='utf-8')
p=R/'changed-files.json';d=json.loads(p.read_text(encoding='utf-8-sig'))
import hashlib
for n in ['core/utils/recipient_resolver.py','core/utils/unified_recipient_resolver.py']:d[n]=hashlib.sha256((W/n).read_bytes()).hexdigest()
p.write_text(json.dumps(d,indent=2),encoding='utf-8')
