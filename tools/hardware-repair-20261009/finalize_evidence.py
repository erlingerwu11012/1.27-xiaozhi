from pathlib import Path
import json,hashlib,tarfile,sqlite3,collections,asyncio,importlib.util,sys
S=Path(__file__).parent;sys.path.insert(0,str(S));from budget import Budget
budget=Budget(S/'budget.sqlite3');rows=[json.loads(x) for x in (S/'final-results.jsonl').read_text().splitlines()]
review={'additional_failed_ids':['holdout-38','holdout-49'],'reason':'Manual review found ordinary chat replaced by operation-error fallback. Candidate fixes passed free protocol regression; not revalidated with paid model.'}
(S/'manual-review.json').write_text(json.dumps(review,indent=2))
f=json.loads((S/'final-freeze.json').read_text());files=json.loads((S/'changed-files.json').read_text(encoding='utf-8-sig'));hashes={n:hashlib.sha256((S/'work'/n).read_bytes()).hexdigest() for n in files}
java=['src/main/java/xiaozhi/modules/personmemory/'+n for n in ['RecentArchiveService.java','PersonMemoryService.java','PersonMemoryController.java']]+['src/main/java/xiaozhi/modules/config/service/impl/ConfigServiceImpl.java']
# Locate the actual ConfigServiceImpl in this repository instead of guessing its package.
java=java[:3]+[str(next((S/'manager-api/src/main/java').rglob('ConfigServiceImpl.java')).relative_to(S/'manager-api'))]
with tarfile.open(S/'candidate-source-only.tgz','w:gz') as t:
 for n in files:t.add(S/'work'/n,arcname='python/'+n)
 for n in java:t.add(S/'manager-api'/n,arcname='java/'+n)
current={'python':hashes,'java':{n:hashlib.sha256((S/'manager-api'/n).read_bytes()).hexdigest() for n in java}}
(S/'candidate-current-sources.json').write_text(json.dumps(current,indent=2));version=hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()[:16]
usage=budget.report();blocked=[x['case']['id'] for x in rows if x['errors']];model_success_turns=sum(any(d.get('usage') for d in x.get('decisions',[])) for x in rows)
release={'passed':False,'deployment_allowed':False,'reason':['final_memory_cases_incomplete_after_model_budget_exhausted','two_chat_defects_fixed_after_final_freeze_without_full_real_model_revalidation'],'candidate_version':version,'planned_final_cases':len(rows),'automatic_pass':sum(not x['errors'] for x in rows),'manual_review_pass':sum(not x['errors'] for x in rows)-2,'manual_review_failed':review['additional_failed_ids'],'incomplete_or_failed_ids':blocked,'actual_model_response_turns':model_success_turns,'current_code_matches_final_test_freeze':hashes==f['source'],'budget':usage,'production_modified':False,'firmware_flashed':False,'source_bundle_sha256':hashlib.sha256((S/'candidate-source-only.tgz').read_bytes()).hexdigest()}
(S/'release-gate.json').write_text(json.dumps(release,ensure_ascii=False,indent=2))
spec=importlib.util.spec_from_file_location('oldrelease','/root/prjs/releases/experience-repair-20261009/release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);health=asyncio.run(m.health(internal=8006,public=True))
(S/'production-unchanged-health.json').write_text(json.dumps({'checks':health,'passed':all(x['passed'] for x in health),'production_changed':False},indent=2));print(json.dumps(release,ensure_ascii=False));print('production_healthy',all(x['passed'] for x in health))
with sqlite3.connect(S/'budget.sqlite3') as d:charges=d.execute("SELECT kind,metadata FROM charges").fetchall()
tokens=collections.Counter();status=collections.Counter()
for kind,meta in charges:
 if kind!='model':continue
 if not meta:status['no_response_recorded']+=1;continue
 x=json.loads(meta);status[str(x.get('status'))]+=1
 for k,v in (x.get('usage') or {}).items():
  if isinstance(v,int):tokens[k]+=v
(S/'usage-summary.json').write_text(json.dumps({'budget':usage,'model_http_status':dict(status),'model_tokens':dict(tokens),'cost_currency_amount':None,'cost_note':'Token usage recorded. Exact billed amount not fetched from ledger; no estimated price substituted.'},indent=2))
# Full dialogue export preserves original errors and later manual review.
text=['# 真实模型模拟对话完整记录','设备为软件模拟；记忆为隔离管理API/数据库；全部失败原文保留。','本批不构成上线通过证据。']
for r in rows:
 text+=['',f"## {r['case']['id']}",f"用户：{r['case']['query']}",f"智能体：{r.get('speech','')}",f"自动检查：{r['errors'] or '通过'}"]
 if r['case']['id'] in review['additional_failed_ids']:text+=['人工复核：失败，普通聊天被误拦。']
 text+=['```json',json.dumps({'results':r.get('outcome',{}).get('results'),'state':r.get('state'),'readback':r.get('readback')},ensure_ascii=False,indent=2),'```']
(S/'complete-dialogues.md').write_text('\n'.join(text))
