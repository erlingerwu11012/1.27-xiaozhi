"""Same single primary model with thinking enabled; no second rewrite or writes."""
from pathlib import Path
source=Path(__file__).with_name('dialogue_fix_acceptance.py').read_text().split('old_guide=')[0]
exec(compile(source,'<thinking-bootstrap>','exec'))
result={'model':'qwen3.8-max','thinking':True,'secondary_rewrite':False,'hardware_writes':0,
        'max_calls':8,'max_input_tokens':40000,'max_completion_tokens':16384,'turns':[]}
questions=['今天两个会都白开了，我有点烦。别给方案，别劝我休息，就随便聊聊。',
 '书架店家下周一才发货，现在还没发，也没收到。我就是期待把以前的书摆出来。',
 '报告之前写好了一半，昨天只改了标题，另一半正文还没写。这能说正文一个字没写吗？',
 '今天先别逗我，也别告诉我慢慢来。我只是说说这些小事。',
 '成年人的朋友为什么越来越难约？直接说你的看法，别反问我。',
 '以前在楼下喊一声就能见面，现在吃个饭都得先看日历。',
 '其实我想要的是像朋友那样自然聊，不是被安慰或者被带着安排。',
 '刚才说的书架现在是什么状态？报告又写到哪了？只按我说过的内容回答。']
p=LLMProvider(dict(llm,model_name='qwen3.8-max',timeout=60));p.client=p.client.with_options(max_retries=0)
messages=[{'role':'system','content':prompt(PERSONA)}]
try:
 for index,text in enumerate(questions,1):
  assert len(result['turns'])<8
  assert sum((r.get('usage')or{}).get('prompt_tokens',0) for r in result['turns'])<40000
  messages.append(user(text));start=time.perf_counter()
  row={'turn':index,'user':text}
  try:
   response=p.client.chat.completions.create(model='qwen3.8-max',messages=messages,tools=definitions,tool_choice='auto',temperature=0.4,max_tokens=2048,extra_body={'enable_thinking':True,'preserve_thinking':False})
   msg=response.choices[0].message
   row.update(assistant=msg.content or '',elapsed_ms=round((time.perf_counter()-start)*1000),
     finish_reason=response.choices[0].finish_reason,tool_proposals=[{'name':t.function.name,'arguments':t.function.arguments} for t in(msg.tool_calls or [])],
     usage=response.usage.model_dump() if response.usage else None,reasoning_returned=bool(getattr(msg,'reasoning_content',None)))
  except Exception as e:row.update(error_type=type(e).__name__,status=getattr(e,'status_code',None))
  result['turns'].append(row);(OUT/'dialogue-fix-thinking-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
  print(json.dumps(row,ensure_ascii=False),flush=True)
  if 'error_type' in row or row.get('tool_proposals') or not row.get('assistant'):break
  messages.append({'role':'assistant','content':row['assistant']})
finally:p.client.close()
result['completed']=len(result['turns'])==8 and all(r.get('assistant') and not r.get('tool_proposals') for r in result['turns'])
(OUT/'dialogue-fix-thinking-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
