from pathlib import Path
p=Path(__file__).parent/'start_api.py';s=p.read_text(encoding='utf-8-sig').replace(" q.execute(\"INSERT IGNORE INTO ai_agent(id", " q.execute(\"INSERT IGNORE INTO ai_agent_template(id,agent_name,sort,vllm_model_id) VALUES('template_http','Isolated test',0,NULL)\")\n q.execute(\"INSERT IGNORE INTO ai_agent(id");p.write_text(s,encoding='utf-8')
