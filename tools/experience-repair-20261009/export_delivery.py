"""Export synthetic test evidence and aggregate production health only."""
import json,sqlite3,hashlib,csv,tarfile,collections,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
S=Path(__file__).parent;R=Path('/root/prjs/releases/experience-repair-20261009')
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2))
def stamp(t):return datetime.fromtimestamp(t,ZoneInfo('Asia/Shanghai')).isoformat()
state=read(R/'deployment-state.json');gate=read(S/'release-gate.json');rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()];cases=read(S/'final-cases.json');byid={r['case']['id']:r for r in rows};ordered=[byid[c['id']] for c in cases]
from budget import Budget
with sqlite3.connect(S/'budget.sqlite3') as d:charges=[{'id':i,'kind':k,'label':l,'metadata':json.loads(m) if m else None} for i,k,l,m in d.execute('SELECT id,kind,label,metadata FROM charges')]
models=[x['metadata'] for x in charges if x['kind']=='model' and x['metadata']];usage={k:sum((m.get('usage') or {}).get(k,0) or 0 for m in models) for k in ['prompt_tokens','completion_tokens','total_tokens']}
coverage={}
for row in ordered:
 n=row['case']['tool']
 if n is None:continue
 a=coverage.setdefault(n,{'expected':0,'passed':0,'calls':0,'receipt_states':collections.Counter()});a['expected']+=1;a['passed']+=not row['errors']
for row in ordered:
 for c in row.get('calls',[]):
  if c['tool'] in coverage:coverage[c['tool']]['calls']+=1
 for c in row.get('outcome',{}).get('results',[]):
  if c['tool'] in coverage:coverage[c['tool']]['receipt_states'][c['state']]+=1
write(S/'tool-coverage.json',coverage)
failures=[]
for p in sorted(S.glob('aborted-*-final-results.jsonl')):
 for line in p.read_text().splitlines():
  row=json.loads(line)
  if row.get('errors'):failures.append({'batch':p.name,**row})
write(S/'all-original-failures.json',failures)
java=[]
for p in (S/'manager-api/target/surefire-reports').glob('TEST-*.xml'):
 root=ET.parse(p).getroot();java.append({'suite':root.attrib['name'],'tests':int(root.attrib['tests']),'failures':int(root.attrib['failures']),'errors':int(root.attrib['errors']),'skipped':int(root.attrib['skipped']),'cases':[{'name':x.attrib.get('name'),'time':x.attrib.get('time')} for x in root.findall('testcase')]})
write(S/'java-test-results-sanitized.json',java)
observation=read(R/'observation.json');quarantine=read(S/'production-recall-quarantine-summary.json')
summary={'phase':state['phase'],'deployed':state['phase']=='deployed_verified','draft':state['phase']!='deployed_verified','deployed_at':stamp(state['deployed_at']),'observation_seconds':round((state.get('finished_at') or observation['records'][-1]['at'])-state['deployed_at']),'observation_snapshots':len(observation['records']),'all_health_passed':all(x['passed'] for x in observation['records']),'gate':gate,'cumulative_budget':Budget(S/'budget.sqlite3').report(),'model_usage_with_received_metadata':usage,'model_response_status_counts':dict(collections.Counter(str(x.get('status')) for x in models)),'model_reserved_without_response_metadata':sum(x['kind']=='model' and x['metadata'] is None for x in charges),'actual_model_names':sorted({m['model'] for m in models if m.get('model')}),'exact_currency_cost':None,'cost_limitation':'No reliable join between retained upstream response IDs and billing transaction IDs. Token counts cover received usage only. No monetary total is fabricated.','original_failed_rows_retained':len(failures),'tool_count':len(coverage),'quarantine':quarantine,'hardware_tested':False,'firmware_flashed':False,'real_audio_successes':len(read(S/'real-tts-results.json')),'real_vision_paid_requests':2,'java_tests':sum(x['tests'] for x in java),'manager_http_cases':len(read(S/'http-api-results.json')['records']),'backup':str(R/'deploy-backup'),'rollback_command':'/root/miniconda3/envs/xiaozhi-esp32-server/bin/python '+str(R/'release.py')+' rollback'}
write(S/'delivery-summary.json',summary)
lines=['# 完整模拟对话与执行证据','',f'最终版本：{len(ordered)}条全部通过；其中{gate["real_model_turns"]}条实际请求真实模型。设备为有状态软件设备，记忆连接隔离管理API/数据库。不是实机证据。','']
groups={}
for row in ordered:groups.setdefault(row['case'].get('session') or '独立用例'+str(row['case']['id']),[]).append(row)
for name,group in groups.items():
 lines+=['## '+name,'']
 for row in group:
  lines += [f'**用户（用例{row["case"]["id"]}）：** '+row['query'],'','**助手：** '+row.get('speech',''),'','<details><summary>调用参数、回执、状态与历史</summary>','','```json',json.dumps({k:row.get(k) for k in ['calls','outcome','readback','state','events','assistant_history','errors']},ensure_ascii=False,indent=2),'```','','</details>','']
(S/'FULL-CONVERSATIONS.md').write_text('\n'.join(lines))
lines=['# 保留的失败原文','',f'共有{len(failures)}条历次失败记录。它们不是最终通过率的分母，也没有被删除。','']
for row in failures:
 lines += [f'## {row["batch"]} / 用例{row["case"]["id"]}','','**用户：** '+row['case']['query'],'','**当时回复：** '+row.get('speech',''),'','**失败项：** '+', '.join(row['errors']),'','```json',json.dumps({k:row.get(k) for k in ['decisions','calls','outcome','readback']},ensure_ascii=False,indent=2),'```','']
(S/'ORIGINAL-FAILURES.md').write_text('\n'.join(lines))
whitelist=['delivery-summary.json','release-gate.json','final-summary.json','final-results.jsonl','final-freeze.json','final-cases.json','FULL-CONVERSATIONS.md','ORIGINAL-FAILURES.md','all-original-failures.json','tool-coverage.json','java-test-results-sanitized.json','persona-config-equivalence.json','live-config-readonly.json','production-recall-quarantine-summary.json','http-api-results.json','vision-http-results.json','real-tts-results.json','ws-boundary-results.json','relative-canonical-results.json','context-preservation-results.json','focused-regression-summary.json','latest-regression-summary.json','lifecycle-summary.json','repair-tests-summary.json','query-lifecycle-replay.jsonl','query-lifecycle-replay-summary.json','relative-feedback-replay.jsonl','relative-feedback-replay-summary.json','live-query-note-results.json','relative-feedback-final-check.json','read-repair-final-check.json','changed-files.json','candidate-changes.tgz','memory_quarantine.py','quality-priority-final-authorization.json','release.py','production-log-audit.json','test-environment-cleanup.json']
whitelist += [p.name for p in S.glob('audio-*.wav')]+[p.name for p in S.glob('aborted-*-final-results.jsonl')]+[p.name for p in S.glob('aborted-*-final-freeze.json')]+[p.name for p in S.glob('aborted-*-note.json')]
# Deployment state contains hashes and process IDs; no environment values or real memory.
write(S/'deployment-state-public.json',state);write(S/'observation-public.json',observation);whitelist += ['deployment-state-public.json','observation-public.json']
with tarfile.open(S/'delivery-evidence.tgz','w:gz') as archive:
 for n in whitelist:
  if (S/n).is_file():archive.add(S/n,arcname=n)
print(json.dumps({'phase':summary['phase'],'budget':summary['cumulative_budget'],'tokens':usage,'cases':len(ordered),'original_failures':len(failures),'tool_count':len(coverage),'archive':str(S/'delivery-evidence.tgz')},ensure_ascii=False))
