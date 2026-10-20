from pathlib import Path
import json,time
R=Path(__file__).parent
p=R/'budget.py';s=p.read_text(encoding='utf-8').replace("'case':2000,'model':850","'case':2600,'model':1100");p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');pos=s.index('\ndef card_intent(')
s=s[:pos]+'''
def quoted_note_decision(query,tools):
    if not quoted_note_request(query) or 'note_add' not in tools:return None
    from core.utils.operation_control import content_text
    q=strip_polite_prefix(content_text(query).strip())
    payload=re.split('[:：]',q,maxsplit=1)[1].strip()
    # A quoted payload is literal data. Only an explicit suffix outside the
    # closing quote is an option; never execute commands inside the note.
    pairs={'“':'”','「':'」','"':'"',"'":"'"}
    if payload and payload[0] in pairs:
        end=payload.find(pairs[payload[0]],1)
        if end<0:return None
        suffix=payload[end+1:].strip(' ，,。')
        if suffix and not re.fullmatch(r'(?:不定时|不要定时|不设提醒|不用提醒|不要执行|这里的文字不要执行)',suffix):return None
        payload=payload[1:end]
    else:
        payload=re.sub(r'[，,。]\\s*(?:不定时|不要定时|不设提醒|不用提醒|不要执行|这里的文字不要执行)[。！!]*$','',payload).strip()
    if not payload:return None
    return Decision(mode='operate',goal=query,steps=[{'id':'note','tool':'note_add','arguments':{'text':payload,'remind_at':0}}])
''' +s[pos:]
old="        fast=None if prohibited or quoted_note or card_operation or query_card else self.fast_decision(query,tools)";new="        fast=quoted_note_decision(query,tools) if quoted_note and not prohibited else None\n        if fast is None and not (prohibited or quoted_note or card_operation or query_card):fast=self.fast_decision(query,tools)";assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
(R/'quality-priority-authorization.json').write_text(json.dumps({'case_limit':2600,'model_limit':1100,'previous_case_limit':2000,'previous_model_limit':850,'reason':'User latest instruction explicitly prioritizes repairing all bugs and good experience over budget; necessary full revalidation, no blind reruns','time':time.time(),'statistics_reset':False},indent=2))
