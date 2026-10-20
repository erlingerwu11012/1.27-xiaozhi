from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
s=s.replace('存(?:个|条)?','存(?:一)?(?:个|条)?')
pos=s.index('\ndef resolve_value(')
s=s[:pos]+'''
def live_read_request(query):
    """Queries must read the accepted request's live device, never stale history."""
    from core.utils.operation_control import content_text
    q=strip_polite_prefix(content_text(query).strip())
    if quoted_note_request(query) or re.search(r'假设|如果|这句话|举例|介绍|怎么|如何|[“”「」]',q):return None
    clauses=re.split('[，,；;。]',q)
    positives=[]
    for clause in clauses:
        clause=re.sub(r'^(?:这次|先|目前|现在|今天|我(?:只是|只想|想|要)?|请|帮我|给我)*','',clause.strip())
        if re.match(r'^(?:不要|别|不用|无需|不必|不改|不动|不调|不设)',clause):continue
        positives.append(clause)
    positive='，'.join(positives)
    if not re.search(r'查|看|确认|多少|多大|几档|什么|啥',positive):return None
    # A query joined to an actual write must remain a full operation plan.
    if re.search(r'调(?:大|小|高|低|亮|暗|到|成)|设(?:为|成|到|置)|改(?:为|成|到)|提高|降低|加.{0,3}(?:点|档|格)|减.{0,3}(?:点|档|格)',positive):return None
    if re.search(r'音量|声音|亮度|几档',positive):return 'self_get_device_status'
    if re.search(r'(?:现在|当前|眼前|显示|这会儿|刚才).{0,10}(?:卡片|提醒)|(?:卡片|提醒).{0,8}(?:什么|啥|内容)',positive):return 'reminder_get_current'
    return None
''' +s[pos:]
s=s.replace('        query_card=current_card_query(query)','        read_request=live_read_request(query)\n        query_card=current_card_query(query) or read_request==\'reminder_get_current\'')
old="        fast=quoted_note_decision(query,tools) if quoted_note and not prohibited else None"
new="""        if read_request=='self_get_device_status' and read_request in tools:
            current=await self.dispatch(read_request,{},scope,turn,epoch,tools,deadline)
            current.intermediate=False;outcome.results.append(current);outcome.reply=current.reply;outcome.interrupted=not self.valid(scope,epoch);return outcome
        fast=quoted_note_decision(query,tools) if quoted_note and not prohibited else None"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'budget.py';s=p.read_text(encoding='utf-8').replace("'model':1100","'model':1400");p.write_text(s,encoding='utf-8')
print('patched live read invariant and explicit note grammar; cases unchanged at 2600; model ceiling 1400 for one final batch')
