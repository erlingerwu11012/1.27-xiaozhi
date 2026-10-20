"""Freeze the incremental acceptance decision and its original evidence versions."""
from pathlib import Path
import collections,json,time
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'final27-results.jsonl').read_text().splitlines()]
assert len(rows)==360 and all(not r['errors'] for r in rows)
assert len({(r['group'],r['turn']) for r in rows})==360
assert sum(r['group'].startswith('combo') for r in rows)==300
origins={}
for p in sorted(S.glob('final*-results.jsonl'),key=lambda p:p.stat().st_mtime):
 for line in p.read_text().splitlines():
  r=json.loads(line);events=r.get('events') or []
  if events:origins.setdefault(events[0]['sentence_id'],p.stem.removesuffix('-results'))
mapping=[]
for r in rows:
 events=r.get('events') or []
 mapping.append({'group':r['group'],'turn':r['turn'],'origin':origins.get(events[0]['sentence_id']) if events else 'unknown','real_model_usage_present':any(d.get('usage') for d in r.get('decisions',[]))})
# Reuse was directly authorized by the user. The final review includes the
# complete combined conversations, not only the automated pass flags.
review=[]
for group in sorted({r['group'] for r in rows if r['group'].startswith('combo')}):
 block=sorted([r for r in rows if r['group']==group],key=lambda r:r['turn'])
 assert len(block)==5
 issue='有一轮不必要的道歉，事实和操作正确' if group=='combo-24' else None
 review.append({'group':group,'experience_defect':bool(issue),'note':issue or '上下文、实际调用、读回、回复及用户反馈逐段审阅通过'})
result={'created':time.time(),'incremental_reuse_authorized':True,'all_same_code_version':False,'cases':360,'automated_passed':360,'combination_dialogues':60,'experience_dialogues_without_defect':59,'experience_rate':59/60,'blocking_fact_or_authorization_defects':[],'evidence_origins':dict(collections.Counter(m['origin'] for m in mapping)),'case_provenance':mapping,'dialogue_review':review,'holdout_note':'20段原保留集已在先前失败和修复中暴露，不再称为未见保留集','paid_budget_stop_preserved':'final26-results.jsonl combo-02 turn4；2400模型上限触发，final27仅重跑此段','latency_reused':'final04-latency.jsonl on final24; subsequent changes only unrelated chat/memory reply filters and release packaging','retrieval_reused':'retrieval02-results.jsonl; retrieval implementation unchanged','tool_coverage_reused':'tools-final16-tools.jsonl plus current affected memory dialogue evidence','cache_evidence':'real provider prompt_tokens_details.cache_creation_input_tokens and cached_tokens; no per-layer hit invention','production_deployment':'pending'}
assert result['experience_rate']>=.95
(S/'acceptance-review27.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({k:result[k] for k in ['cases','automated_passed','experience_dialogues_without_defect','experience_rate','evidence_origins']},ensure_ascii=False))
