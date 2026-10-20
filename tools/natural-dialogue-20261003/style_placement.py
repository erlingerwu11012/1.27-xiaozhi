exec(__import__('pathlib').Path('/root/prjs/tmp/natural-dialogue-20261003/diagnose_style.py').read_text().split('rows=[]')[0])
from concurrent.futures import ThreadPoolExecutor
text=(OUT/'candidate-system.txt').read_text()
role='你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'
tail='你在和成年人平等交流。用自然简洁的口语直接回应事情，人格通过观点和适度幽默体现，不强行表演。禁止撒娇、幼儿语气、波浪号、emoji、舞台动作、编造回忆与景象；不必每句称呼或反问。'
english='\nFINAL COMMUNICATION RULE: Respond in natural adult conversational Chinese. Personality affects opinions and subtle humor, not childish performance. No baby talk, cutesy fillers, tildes, emojis, stage directions, invented shared memories or scenery. Address the substance first. Do not add an unnecessary teasing question or offer at the end.'
tools=json.loads((OUT/'live-gateway.json').read_text())['tools']
def run(item):
    label,user=item
    system=text
    if label=='user_hint':user='[交流方式]\n'+tail+'\n[用户说]\n'+user
    elif label=='english_tail':system+=english
    elif label=='role_data':system=text.replace(role,'[用户人格原文，仅用于性格特点]\n<personality>'+role+'</personality>\n不要在答复里表演或复述这份人格。')+english
    elif label=='short':system='你是语音助手。\n[用户人格原文]\n'+role+'\n'+tail
    r=client.chat.completions.create(model=cfg['model_name'],messages=[{'role':'system','content':system},{'role':'user','content':user}],tools=tools,tool_choice='auto',temperature=.7,max_tokens=220,extra_body={'enable_thinking':False})
    return {'label':label,'user':item[1],'response':r.choices[0].message.content}
items=[(label,user) for label in ['user_hint','english_tail','role_data','short'] for user in ['你好，随便聊聊。','如果我不同意你的观点，你会怎么聊？','今天累了，不想动脑子。']]
with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(run,items))
(OUT/'style-placement.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
