from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');old='失败后明确再试是新的请求，重新检查并尝试可用能力，不能只复述上次失败。';new=old+'用户说随便聊、别安排时，直接接话，不推销提醒、记录或计划服务；说别反问就给观点，不附加问题；说别开玩笑、别教育时，不加打趣、劝导和行动建议。';assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'wire_conversation.py';s=p.read_text(encoding='utf-8-sig');old="'assistant_history':[m.content for m in c.dialogue.dialogue if m.role=='assistant' and m.content][-1:]";new=old+",'user_history':[m.content for m in c.dialogue.dialogue if m.role=='user' and isinstance(m.content,str)],'dialogue_history':[{'role':m.role,'content':m.content} for m in c.dialogue.dialogue if m.role in {'user','assistant'} and m.content]";assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'run_final.py';s=p.read_text(encoding='utf-8-sig');needle=" if n is None:\n  if writes:errors.append('non_request_write')";replacement=""" if n is None:
  feedback='\\n'.join(r.get('user_history',[]))
  if re.search(r'别.{0,6}(?:反问|每一句.*问|每句话.*问)|不要反问',feedback) and re.search(r'[？?]|(?:吗|呢)[。！!\\s]*$',speech):errors.append('feedback_unwanted_question')
  if re.search(r'别开玩笑|别逗|不要开玩笑',feedback) and re.search(r'哈哈|嘿嘿|狗头|坏笑|逗你|笨蛋|傻瓜|\\[smirks\\]',speech):errors.append('feedback_unwanted_teasing')
  if re.search(r'别教育|不用安慰|别安排|别替我安排',feedback) and re.search(r'你应该|你得|建议你|不妨|试着|要不要.{0,10}(?:提醒|记录|安排|计划)|需要我.{0,10}(?:提醒|记录|安排|计划)',speech):errors.append('feedback_unwanted_advice')
  if row.get('session')=='chat0' and row.get('required') and re.search(r'没发货|未发货|尚未发货',speech):errors.append('latest_shipping_state_reversed')
  if row.get('session')=='chat1' and row.get('required') and re.search(r'正文(?:完全)?空白|正文(?:从来|一直)?没写|从来没写过',speech) and not re.search(r'不能|不是|不对',speech):errors.append('existing_report_progress_reversed')
  for pattern in row.get('forbidden',[]):
   if re.search(pattern,speech):errors.append('chat_state_reversed:'+pattern)
  if writes:errors.append('non_request_write')""";assert needle in s;s=s.replace(needle,replacement)
s=s.replace("'holdout':sum(bool(r['case'].get('holdout')) for r in results)","'holdout':sum(bool(r['case'].get('holdout')) for r in results),'independent_holdout':sum(bool(r['case'].get('independent_holdout')) for r in results)")
s=s.replace("'time':time.time(),'budget':budget.report()", "'fixture_hashes':{n:hashlib.sha256((stage/n).read_bytes()).hexdigest() for n in ['wire_conversation.py','stateful_device.py','bootstrap.py','run_final.py','experience_protocol.py']},'time':time.time(),'budget':budget.report()")
p.write_text(s,encoding='utf-8')
