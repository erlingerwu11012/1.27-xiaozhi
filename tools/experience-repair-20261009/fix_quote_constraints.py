from pathlib import Path
S=Path('tools/experience-repair-20261009');p=S/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');s=s.replace('麻烦|请你|请|帮我|给我|能不能','麻烦|请你|请|帮我|给我|替我|能不能',1)
pos=s.index('\ndef resolve_value(')
s=s[:pos]+'''
def quoted_note_request(query):
    from core.utils.operation_control import content_text
    q=strip_polite_prefix(content_text(query).strip())
    return bool(re.match(r'^(?:只)?(?:保存|记录|记(?:一)?条|记下|写(?:一)?条|加(?:一)?条|新建|存(?:个|条)?)(?:便签|备忘录)(?:内容)?[:：]',q))

'''+s[pos:]
s=s.replace("    from core.utils.operation_control import parse_request,CONTRACTS,content_text\n    q=content_text(query)","    if quoted_note_request(query):return {}\n    from core.utils.operation_control import parse_request,CONTRACTS,content_text\n    q=content_text(query)",1)
s=s.replace("    from core.utils.operation_control import content_text\n    from core.utils.remind_time", "    if quoted_note_request(query):return {}\n    from core.utils.operation_control import content_text\n    from core.utils.remind_time",1)
s=s.replace("        quoted_note=bool(re.search(r'(?:保存|记录|记(?:一)?条|记下|写(?:一)?条|加(?:一)?条|新建|存(?:个|条)?)(?:便签|备忘录)(?:内容)?[:：]',plain))","        quoted_note=quoted_note_request(query)",1)
s=s.replace("        fast=None if prohibited else self.fast_decision(query,tools)","        fast=None if prohibited or quoted_note else self.fast_decision(query,tools)",1)
s=s.replace("        if re.match(r'^(?:只)?(?:保存|记录)(?:便签|备忘录)[:：]',strip_polite_prefix(q)):","        if quoted_note_request(query):",1)
s=s.replace("        if re.match(r'^(?:只)?(?:保存|记录)(?:便签|备忘录)[:：]',q):return False","        if quoted_note_request(query):return False",1)
p.write_text(s,encoding='utf-8')
