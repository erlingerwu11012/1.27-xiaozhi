from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
pos=s.index('\ndef resolve_value(')
s=s[:pos]+'''
def reply_preferences(statements):
    no_questions=False
    for text in statements:
        text=re.sub(r'[“「][^”」]*[”」]','',str(text))
        if re.search(r'别.{0,6}(?:反问|追问)|不要.{0,6}反问|别每.{0,8}问|不用.{0,6}反问',text):no_questions=True
        if re.search(r'(?:可以|也行|欢迎)(?:再)?问我|你问吧|你可以问',text):no_questions=False
    return {'no_optional_questions':no_questions}

def respect_chat_preferences(reply,preferences):
    if not preferences.get('no_optional_questions'):return reply
    # Only remove optional chat questions. Necessary operation clarification
    # has a separate mode and never passes through this presentation rule.
    parts=re.findall(r'[^。！？!?]+[。！？!?]*',str(reply))
    kept=[p for p in parts if not re.search(r'[？?]|(?:吗|呢)[。！!\\s]*$',p)]
    return ''.join(kept).strip() or '好，我直接接着说。'
''' +s[pos:]
s=s.replace("        if results:context['verified_results']", "        context['reply_preferences']=getattr(self,'_reply_preferences',{})\n        if results:context['verified_results']")
old="        return Decision.model_validate(await asyncio.wait_for(asyncio.to_thread(self.decide,messages),remaining))"
new="""        raw=await asyncio.wait_for(asyncio.to_thread(self.decide,messages),remaining)
        if isinstance(raw,dict):
            for step in raw.get('steps',[]):
                if isinstance(step,dict) and step.get('tool') in getattr(self,'_relative_constraints',{}):
                    # Explicit user magnitude/direction outranks a model's
                    # guessed number, boolean, or reference. Execution still
                    # reads actual state and applies the domain bounds.
                    step['relative']=self._relative_constraints[step['tool']]
                    step['arguments']={};step.pop('extreme',None)
        return Decision.model_validate(raw)"""
assert old in s;s=s.replace(old,new)
old="        adjustments={} if quoted_note else relative_requirements(query)"
new="""        adjustments={} if quoted_note else relative_requirements(query)
        self._relative_constraints=copy.deepcopy(adjustments)
        actor_key=getattr(actor,'key',None)
        statements=[m.content for m in getattr(getattr(self.conn,'dialogue',None),'dialogue',[]) if m.role=='user' and getattr(m,'material_actor_key',None)==actor_key and isinstance(m.content,str)][-8:]
        self._reply_preferences=reply_preferences(statements+[query])"""
assert old in s;s=s.replace(old,new)
s=s.replace("else decision.reply\n                    outcome.interrupted", "else respect_chat_preferences(decision.reply,self._reply_preferences) if decision.mode=='chat' else decision.reply\n                    outcome.interrupted")
p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/models.py';s=p.read_text(encoding='utf-8');s=s.replace('relative:int|None=None','relative:int|None=Field(default=None,strict=True)');p.write_text(s,encoding='utf-8')
p=R/'package_candidate.py';s=p.read_text(encoding='utf-8').replace("'core/utils/tool_harness/runtime.py'","'core/utils/tool_harness/models.py','core/utils/tool_harness/runtime.py'");p.write_text(s,encoding='utf-8')
p=R/'budget.py';s=p.read_text(encoding='utf-8').replace("'case':3300,'model':1700","'case':4000,'model':2000");p.write_text(s,encoding='utf-8')
