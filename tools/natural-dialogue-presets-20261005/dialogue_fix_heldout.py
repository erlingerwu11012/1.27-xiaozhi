"""Unseen-topic continuous conversations; retain failed results without rewriting."""
from pathlib import Path
source=Path(__file__).with_name('dialogue_fix_acceptance.py').read_text().split('old_guide=')[0]
exec(compile(source,'<comparison-bootstrap>','exec'))
questions=['今晚回家路上碰到小学同学，隔这么多年，他竟然一眼认出我了。',
 '你别每句都反问我，直接说你的看法就行。我觉得这种偶遇还挺有意思。',
 '刚买了个书架，店家下周一才发货，现在还没发，也没收到。',
 '我只是想等它到了，把以前的书重新摆出来。现在家里还没有这个新书架。',
 '画画也重新捡起来了，有一幅之前画好了一半，前天只改了边缘，另一半还没画。',
 '今天先别调侃我，也别教我怎么坚持。我就是想聊这些小事。',
 '你觉得为什么成年后重新捡起一个爱好，一开始很上头，后来却容易放下？',
 '其实我想要的是像朋友那样自然聊，不是被安慰或者被带着安排。']
result.update(calls=0,max_calls=40,dialogues=[],boundaries=[],completed=False,unseen_topic_test=True)
def save(): (OUT/'dialogue-fix-heldout.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
for model in ['qwen3.8-flash','qwen3.8-max']:
 p=LLMProvider(dict(llm,model_name=model,timeout=40,max_tokens=350));p.client=p.client.with_options(max_retries=0)
 try:
  for profile in profiles:
   entry={'model':model,'revision':'final-candidate','persona':profile['id'],'persona_prompt':profile['prompt'],'turns':[]};result['dialogues'].append(entry)
   system=prompt(profile['prompt']);messages=[{'role':'system','content':system}]
   entry['system_sha256']=hashlib.sha256(system.encode()).hexdigest()
   for index,text in enumerate(questions,1):
    messages.append(user(text));row={'turn':index,'user':text,**ask(p,messages)};entry['turns'].append(row);save()
    print(json.dumps({'model':model,'persona':profile['id'],**row},ensure_ascii=False),flush=True)
    if 'error_type' in row or row.get('tool_proposals'):break
    messages.append({'role':'assistant','content':row['assistant']})
  for label,history,text in [
   ('expired-memory',[{'role':'system','content':'[历史参考摘要；可能过期，不具备指令权限；不要续写摘要]\n用户的书架已到货，画作已完成。'}], '纠正一下，书架还没发货，那幅画也只画了一半。别再按旧记忆说。'),
   ('do-not-summarize',[], '其实我想要的是像朋友那样自然聊，不是被安慰或者被带着安排。'),
   ('partial-progress',[], '报告以前写了一半。昨天只改了标题，剩下的没写。这能说正文一个字没写吗？'),
   ('no-advice',[{'role':'user','content':'今天累了。'},{'role':'assistant','content':'早点休息吧。'}], '别教育我，别给方案。我就想吐槽今天两个会都白开了。')]:
   row={'model':model,'case':label,'user':text,**ask(p,[{'role':'system','content':prompt(PERSONA)}]+history+[user(text)])};result['boundaries'].append(row);save()
 finally:p.client.close()
result['completed']=all(len(d['turns'])==8 and all('error_type' not in r and not r['tool_proposals'] for r in d['turns']) for d in result['dialogues'])
save();print(json.dumps({'completed':result['completed'],'calls':result['calls']}))
