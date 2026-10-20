from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');needle="    if re.search(r'(?:现在|当前|眼前|显示|这会儿|刚才).{0,10}(?:卡片|提醒)";a=s.index(needle)
s=s[:a]+"    if '卡片' in positive and re.search(r'查|状态|是不是|是否|有没有|还在|还挂|关没关|关闭.{0,3}吗|收起来.{0,3}吗',positive) and not re.search(r'(?:把|将).{0,20}(?:关掉|关闭|收起)|(?:^|[，,；;])(?:再|然后)?(?:关掉|关闭|收起)',positive):return 'reminder_get_current'\n"+s[a:]
s=s.replace("if re.search(r'卡片.{0,8}(?:关|关闭|收起)|(?:关|关闭|收起).{0,8}卡片',q) and not re.search(r'别关|不要关|不用关|怎么|如何',q):", "if live_read_request(q)!='reminder_get_current' and re.search(r'卡片.{0,8}(?:关|关闭|收起)|(?:关|关闭|收起).{0,8}卡片',q) and not re.search(r'别关|不要关|不用关|怎么|如何',q):")
needle='def reply_preferences(statements):';insert='''def chat_fact_conflict(reply,messages,query):
    from core.utils.operation_control import content_text
    statements=[content_text(m.get('content','')) for m in messages if m.get('role')=='user']+[content_text(query)]
    source=next((q for q in reversed(statements) if re.search(r'(?:写好|写完|写了|完成(?:了)?|做了).{0,6}(?:一半|50[%％])',q) and not re.search(r'[？?]|不是一半|没到一半|如果|假设',q)),None)
    if source and (re.search(r'报告|正文|进度|完成|写',query) or re.search(r'报告|正文|进度',reply)):
        # Later explicit completion supersedes an older half-complete statement.
        later=statements[statements.index(source)+1:]
        updated=any(re.search(r'(?:报告|正文).{0,10}(?:全部写完|都写完|已经完成|全部完成)|(?:报告|正文).{0,10}(?:三分之二|大半|百分之|\\d+[%％])',q) and not re.search(r'[？?]|没|未|不|如果',q) for q in later)
        if not updated and re.search(r'大半|大部分|(?:全部|全都|都)(?:写好|写完|完成)|100[%％]',reply) and not re.search(r'还没|尚未|不是|未完成',reply):return source
    if '上周' in query and re.search(r'昨天.{0,5}只改.{0,3}标题',query) and re.search(r'上周[^，,。；;]{0,15}(?:停留|主要|只是|只)[^，,。；;]{0,10}标题',reply):return query
    return None

''';s=s.replace(needle,insert+needle,1)
needle="                    prior_text=next((m.get('content')";a=s.index(needle);s=s[:a]+"                    if decision.mode=='chat' and not outcome.results:\n                        source=chat_fact_conflict(decision.reply,messages,query)\n                        if source:\n                            self._chat_fact_source=source\n                            raise ValueError('chat_fact_conflicts_with_user_statement_preserve_exact_progress_and_time')\n"+s[a:]
needle="        meaningful=[r for r in outcome.results";a=s.index(needle);s=s[:a]+"        if outcome.error.startswith('chat_fact_conflicts_with_user_statement') and not outcome.results:\n            outcome.mode='chat';outcome.reply='你说的是：'+self._chat_fact_source.rstrip('。')+'。'\n            outcome.interrupted=not self.valid(scope,epoch);return outcome\n"+s[a:];p.write_text(s,encoding='utf-8')
p=R/'run_model.py';s=p.read_text(encoding='utf-8').replace("  feedback='\\n'.join", "  from core.utils.tool_harness.runtime import chat_fact_conflict\n  if chat_fact_conflict(speech,r.get('dialogue_history',[]),row['query']):errors.append('chat_fact_progress_conflict')\n  feedback='\\n'.join");p.write_text(s,encoding='utf-8')
