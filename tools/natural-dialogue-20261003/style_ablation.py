"""Six controlled requests isolate style priming without editing personality."""
exec(__import__('pathlib').Path('/root/prjs/tmp/natural-dialogue-20261003/diagnose_style.py').read_text().split('rows=[]')[0])
text=(OUT/'candidate-system.txt').read_text()
role='你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'
no_name=re.sub(r'账号设置的称呼:[^\n]*\n','',text)
no_tags=re.sub(r'\[官方语音表达\][\s\S]*?(?='+re.escape(role)+')','',no_name)
no_events=no_tags[no_tags.index('[对话方式]'):]
tail='\n[当前表达方式]\n只用成年人正常交流的语气，直接回应用户，不表演角色性格。使用正常标点，不使用波浪号、emoji、动作旁白或情绪标签，不猜用户心理，不虚构动作、回忆或周围环境。回答结束就停，无需追加玩笑或问题。人格在观点和自然措辞中体现。'
rows=[]
for label,system in [('no_name',no_name),('no_tags',no_tags),('no_events',no_events),('no_name_tail',no_name+tail),('no_events_tail',no_events+tail),('short_tail',role+tail)]:
    r=client.chat.completions.create(model=cfg['model_name'],messages=[{'role':'system','content':system},{'role':'user','content':'你好，随便聊聊。'}],tools=json.loads((OUT/'live-gateway.json').read_text())['tools'],tool_choice='auto',temperature=.7,max_tokens=220,extra_body={'enable_thinking':False})
    rows.append({'label':label,'response':r.choices[0].message.content,'length':len(system)})
(OUT/'style-ablation.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False))
