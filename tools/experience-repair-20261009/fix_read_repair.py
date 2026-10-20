from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
pos=s.index('\ndef resolve_value(')
s=s[:pos]+'''
def explicit_list_query(query):
    from core.utils.operation_control import content_text
    q=content_text(query)
    if quoted_note_request(query) or Harness.non_request(q):return set()
    if re.search(r'删除|删掉|删了|取消|新增|创建|设个|设一个|设置一个|定个|定一个|推迟|延后|写条|完成|调整|调到|改为|改成|增加|减少',q):return set()
    if not re.search(r'查|看|列表|哪些|什么|还有|有没有|多少',q):return set()
    return {name for noun,name in [('便签|备忘录','note_list'),('闹钟','alarm_list'),('习惯','habit_list')] if re.search(noun,q)}
''' +s[pos:]
old="        if isinstance(raw,dict):\n            for step in raw.get('steps',[]):"
new="""        if isinstance(raw,dict):
            query_tools=getattr(self,'_explicit_query_tools',set())
            steps=raw.get('steps',[])
            if query_tools and steps and all(isinstance(step,dict) and step.get('tool') in query_tools for step in steps):
                raw['authorized_writes']=[];raw['finished']=True
            for step in steps:"""
assert old in s;s=s.replace(old,new)
s=s.replace("        self._relative_constraints=copy.deepcopy(adjustments)","        self._relative_constraints=copy.deepcopy(adjustments)\n        self._explicit_query_tools=explicit_list_query(query)")
old="if fp in dispatched:raise ValueError('duplicate_step')";new="if fp in dispatched and contract(name).write:raise ValueError('duplicate_step')";assert old in s;s=s.replace(old,new)
old="                        for result in outcome.results:\n                            if not contract(result.tool).write:result.intermediate=False"
new="""                        seen_reads=set()
                        for result in reversed(outcome.results):
                            if not contract(result.tool).write:
                                key=Ledger.fingerprint(result.tool,result.arguments)
                                result.intermediate=key in seen_reads;seen_reads.add(key)"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'budget.py';s=p.read_text(encoding='utf-8').replace("'case':4000,'model':2000","'case':4300,'model':2200");p.write_text(s,encoding='utf-8')
