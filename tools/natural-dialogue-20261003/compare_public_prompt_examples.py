"""Synthetic example-guided prompt experiment. No production prompt or config writes."""
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
source=(OUT/'compare_qwen_models.py').read_text()
exec(compile(source.split("for model in ['qwen-plus'")[0],str(OUT/'compare_qwen_models.py'),'exec'))
system='''你叫小智，与用户用中文日常交谈。把用户当作有自主判断的成年人，先接住这一句话，再决定是否需要多说。
对话质量规则优先于人格的表演：
- 尊重已知事实。计划还没有发生；未知的物品、经历和状态不补写。工具操作只用可用的结构化tool_calls，成功之前不报告完成，没有该工具就说目前做不了。
- 人格影响措辞，不要求每句都调侃。用户疲惫、烦躁或明确不想开玩笑时，保持分寸；用户纠正语气时直接调整，不顶嘴、不反讽、不借玩笑继续指责。
- 闲聊通常一两句；用户明确问建议时再认真给出适度建议。不要用每轮追问、清单、安排来推动对话。不开场表演，不写动作、表情标签、撒娇语气或虚拟身体行为。
以下是用户自主选择的人格原文，保持它，但在上述对话分寸内自然体现：
<personality>你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。</personality>
下面的片段仅示范分寸，不是固定答案；根据当轮用户内容独立接话。
用户：今天累得不想动。
小智：那今天就歇会儿，事情又不会自己跑来找你。
用户：别劝我，也别教我怎么休息。
小智：行，不劝。今天确实够折腾的。
用户：我准备吃点东西再去睡。
小智：这个安排挺舒服的，忙了一天总算能松口气。
用户：别拿我开玩笑了。
小智：好，刚才说过头了，我收住。
用户：本来要整理相册，结果又没做。
小智：相册还没整理，照片倒是越攒越多了。
用户：那你说我现在要不要弄？
小智：不赶时间的话，今晚放一放也行；要是明天就得用，现在挑几张先弄好。
'''
report.update(prompt_source='synthetic public rules plus public examples; not production prompt',system_prompt=system,
 system_characters=len(system),system_sha256=hashlib.sha256(system.encode()).hexdigest(),call_limit=24,calls=0,models=[])
scenes=[('熟悉场景',['今天累了一天，啥也不想干。','别给我灌鸡汤，也别给方案，就随便聊两句。','我点了外卖，吃完洗澡，然后躺着。']),
 ('新措辞场景',['本来想收拾厨房，结果一晚上都在看短视频。','你又在挤兑我了，今天别逗我。','我说洗碗机明天才到，你怎么说我已经用上了？'])]
for model in ['qwen-plus','qwen3.8-flash','qwen3.8-max','qwen3.7-plus']:
 entry={'requested_model':model,'scenes':[]};report['models'].append(entry)
 for title,inputs in scenes:
  messages=[{'role':'system','content':system}];rows=[];entry['scenes'].append({'title':title,'turns':rows})
  for text in inputs:
   messages.append(user(text));row={'user':text,**call(model,messages)};rows.append(row)
   (OUT/'qwen-public-prompt-experiment.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
   print(json.dumps({'model':model,'scene':title,**row},ensure_ascii=False),flush=True)
   if 'error' in row:break
   messages.append({'role':'assistant','content':row['assistant']})
print(json.dumps({'completed':True,'calls':report['calls']}),flush=True)
