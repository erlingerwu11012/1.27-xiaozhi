from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
s=s.replace('(?:保存|记录|记(?:一)?条|记下|写(?:一)?条|加(?:一)?条|新建|存(?:一)?(?:个|条)?)','(?:保存|记录|记下|记|写|加|新建|存)(?:一)?(?:个|条)?')
s=s.replace("        if read_request=='self_get_device_status' and read_request in tools:","        memory_query=memory_read_request(query)\n        if memory_query and 'memory_search' in tools:\n            current=await self.dispatch('memory_search',{'query':memory_query},scope,turn,epoch,tools,deadline)\n            current.intermediate=False;outcome.results.append(current);outcome.reply=current.reply;outcome.interrupted=not self.valid(scope,epoch);return outcome\n        if read_request=='self_get_device_status' and read_request in tools:")
pos=s.index('\ndef resolve_value(');s=s[:pos]+'''
def memory_read_request(query):
    from core.utils.operation_control import content_text
    q=strip_polite_prefix(content_text(query).strip())
    if quoted_note_request(query) or Harness.non_request(q):return None
    if re.search(r'忘掉|忘记|遗忘|删|更正|纠正|改成|改为|记住|保存|记录|[“”「」]',q):return None
    if re.search(r'闹钟|便签|提醒|音量|亮度|设备|习惯|拍照|相机|天气|新闻',q):return None
    if re.search(r'(?:查|搜|检索).{0,25}(?:我|记忆|以前|之前)|你还记得|记忆库',q):return q
    return None
''' +s[pos:]
s=s.replace("'删除|取消|停止|推迟|查看|查询|列出|已设置|设置的'","'删除|取消|停止|推迟|查看|查询|列出|已设置|设置的|设置了(?:哪|什么|几)|设置过(?:哪|什么|几)'")
old="                if decision.mode in {'chat','clarify'}:\n"
new="""                if decision.mode in {'chat','clarify'}:
                    if decision.mode=='chat' and outcome.results and not required_writes:
                        # A pure query's read receipt is its final result. A
                        # planning continuation flag must not hide that result.
                        for result in outcome.results:
                            if not contract(result.tool).write:result.intermediate=False
                        break
"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/recent_memory.py';s=p.read_text(encoding='utf-8');s=s.replace("        if message.role=='system' or getattr(message,'material_turn_id',None)==actor.turn_id:","        if message.role=='system':")
old="            if match in text:\n                message.content=text.replace(match,replacement if action=='correct' else '（该个人信息已按要求移除）')"
new="""            variants=[match]
            if action=='forget' and match.startswith('我的') and len(match)>6:variants.append(match[2:])
            for value in variants:
                if value in text:text=text.replace(value,replacement if action=='correct' else '（该个人信息已按要求移除）')
            message.content=text"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'budget.py';s=p.read_text(encoding='utf-8').replace("'case':2600,'model':1400","'case':3300,'model':1700");p.write_text(s,encoding='utf-8')
print('patched query goal inference, pure read outcome, memory lookup and current forget history')
