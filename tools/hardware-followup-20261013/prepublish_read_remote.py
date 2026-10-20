from pathlib import Path
import json,statistics,math,shutil,subprocess,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s));from budget import Budget
b=list(map(json.loads,(s/'baseline01-latency.jsonl').read_text().splitlines()));c=list(map(json.loads,(s/'candidate01-latency.jsonl').read_text().splitlines()))
assert len(b)==len(c)==20 and [r['query'] for r in b]==[r['query'] for r in c]
def p95(v):return sorted(v)[math.ceil(.95*len(v))-1]
report={'text_baseline_p50':statistics.median(r['first_text_seconds'] for r in b[:12]),'text_candidate_p50':statistics.median(r['first_text_seconds'] for r in c[:12]),'tool_baseline_p95':p95([r['total_seconds'] for r in b[12:]]),'tool_candidate_p95':p95([r['total_seconds'] for r in c[12:]]),'audio_baseline_matched_p50':statistics.median(r['real_audio']['first_audio_seconds'] for r in b[:4]),'audio_candidate_matched_p50':statistics.median(r['real_audio']['first_audio_seconds'] for r in c[:4]),'audio_baseline_n':4,'audio_candidate_n':6,'audio_matched_n':4,'percentile_method':'nearest rank; 8 tool samples; small sample only'}
report['tool_gate']=report['tool_candidate_p95']<=1.1*report['tool_baseline_p95'];report['audio_gate']=report['audio_candidate_matched_p50']<=report['audio_baseline_matched_p50'];(s/'latency-comparison.json').write_text(json.dumps(report,indent=2));print('latency',report)
print('budget',Budget().report(),'free',shutil.disk_usage('/').free)
for a in json.loads(subprocess.check_output(['pm2','jlist'])):
 if a['pm_id'] in [9,10]:print('formal',a['pm_id'],a['pid'],a['pm2_env']['status'],a['pm2_env']['pm_exec_path'])
print('wrapper',Path('/root/prjs/releases/harness-followup-20261013/serve.py').read_text())
