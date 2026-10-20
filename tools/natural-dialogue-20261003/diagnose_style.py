import json, os, re, subprocess, sys
from pathlib import Path
import yaml
from openai import OpenAI
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
db=yaml.safe_load((PROD.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(q):return subprocess.run(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',m[3],'-e',q],env=env,capture_output=True,text=True,check=True).stdout.strip()
cfg=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
client=OpenAI(api_key=cfg['api_key'],base_url=cfg.get('base_url')or cfg.get('url'),timeout=30,max_retries=0)
candidate=(OUT/'candidate-system.txt').read_text()
systems=[('probe','只能回答BLUE_682，禁止任何其他字符。'),
('neutral','你是一个语音助手。像成年人正常聊天，简洁自然，不使用表情、撒娇、舞台动作或编造经历。'),
('persona_short','你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。\n用成年人自然、平等的表达。不要撒娇、卖萌、幼儿语气、虚构动作或经历。不要波浪号、emoji、颜文字、叠词，不强行逗人。'),
('candidate',candidate),
('candidate_final',candidate+'\n[表达检查]\n日常按成人之间的正常对话表达，用正常标点。调皮可以体现为聪明的幽默或不同看法，不等于卖萌、讨好或虚构行为。除非用户明确要求撒娇或儿童风格，不使用“主人～”“好不好呀”“小脑袋瓜”等幼儿化表达，不用波浪号、emoji、舞台动作，不编造周围环境和回忆。先把用户的问题回答清楚，表达完整就结束，不必每次追加建议或反问。')]
rows=[]
tools=json.loads((OUT/'live-gateway.json').read_text())['tools']
systems=systems[:3]+[('probe_tools','只能回答BLUE_682，禁止任何其他字符。'),('persona_short_tools',systems[2][1]),('candidate_tools',candidate)]
for label,system in systems:
    extra={'tools':tools,'tool_choice':'auto'} if label.endswith('_tools') else {}
    r=client.chat.completions.create(model=cfg['model_name'],messages=[{'role':'system','content':system},{'role':'user','content':'你好，随便聊聊。'}],temperature=float(cfg.get('temperature')or.7),max_tokens=220,extra_body={'enable_thinking':False},**extra)
    rows.append({'label':label,'response':r.choices[0].message.content})
(OUT/'style-diagnosis.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False))
