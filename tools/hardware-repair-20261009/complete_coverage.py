from pathlib import Path
import json,signal,os,time
S=Path(__file__).parent;pid=168393;p=Path('/proc')/str(pid)/'cmdline'
if p.exists():
 assert str(S/'run_model.py').encode() in p.read_bytes();os.kill(pid,signal.SIGTERM)
for n in ['final-results.jsonl','final-freeze.json','final-console.log']:
 p=S/n
 if p.exists():p.rename(S/('coverage-check-'+n))
p=S/'final-cases.json';rows=json.loads(p.read_text());rows.append({'id':'coverage-habit-learn','query':'把已分析确认的喝水规律保存为每天上午8点的习惯规则，提前2分钟，来源auto','tool':'habit_learn','arguments':{'intent':'drink_water','description':'喝水','hour':8,'minute':0,'advance_minutes':2,'source':'auto','repeat_days':127},'group':'tool','setup':'habit_learn','holdout':False,'independent_holdout':False})
assert len({x['tool'] for x in rows if x['tool']})==44
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('cases',len(rows),'tool_count',44)
