from pathlib import Path
import json,hashlib,sqlite3,collections,tarfile,time,sys
S=Path(__file__).parent;sys.path.insert(0,str(S));from budget import Budget
rows=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()];order={x['id']:i for i,x in enumerate(json.loads((S/'final-cases.json').read_text()))};rows.sort(key=lambda r:order[r['case']['id']]);f=json.loads((S/'resume-final-freeze.json').read_text())
if len(rows)!=len(order):raise RuntimeError('final incomplete')
audit=json.loads((S/'resume-holdout-audit.json').read_text());assert audit['passed'] and audit['results_sha256']==hashlib.sha256((S/'resume-final-results.jsonl').read_bytes()).hexdigest()
failed=[x['case']['id'] for x in rows if x['errors']];positives=[x for x in rows if x['case']['tool'] and not (x['case'].get('setup')=='photo_retry' and x['case'].get('multi_step')==0)]
common={'memory_correct','memory_forget','self_audio_speaker_set_volume','self_screen_set_brightness','add_reminder','alarm_set','note_add','reminder_get_current','reminder_close_current','reminder_action'}
counts=collections.defaultdict(lambda:{'cases':0,'pass':0})
for x in positives:counts[x['case']['tool']]['cases']+=1;counts[x['case']['tool']]['pass']+=not x['errors']
durations=sorted(x['duration_ms'] for x in rows if 'duration_ms' in x);models=collections.Counter(x.get('outcome',{}).get('model_calls',0) for x in rows)
summary={'cases':len(rows),'passed':len(rows)-len(failed),'failed_ids':failed,'positive_cases':len(positives),'positive_pass':sum(not x['errors'] for x in positives),'common_cases':sum(x['case']['tool'] in common for x in positives),'common_pass':sum(x['case']['tool'] in common and not x['errors'] for x in positives),'per_tool':dict(counts),'tools':len(counts),'real_model_response_turns':sum(any(d.get('usage') for d in r.get('decisions',[])) for r in rows),'independent_holdout':audit['audited_independent_count'],'holdout_marking_audit':'resume-holdout-audit.json','latency_ms':{'p50':durations[len(durations)//2],'p95':durations[int(len(durations)*.95)],'max':max(durations)},'model_calls_per_turn':dict(models),'repairs':sum(x.get('outcome',{}).get('repairs',0) for x in rows),'budget':Budget(S/'budget.sqlite3').report(),'hardware':False}
(S/'resume-acceptance-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
with sqlite3.connect(S/'budget.sqlite3') as d:charges=d.execute('SELECT kind,metadata FROM charges').fetchall()
tokens=collections.Counter();states=collections.Counter();models_reported=collections.Counter()
for kind,metadata in charges:
 if kind!='model':continue
 if not metadata:states['no_response_recorded']+=1;continue
 x=json.loads(metadata);states[str(x.get('status'))]+=1
 if x.get('model'):models_reported[x['model']]+=1
 for k,v in (x.get('usage') or {}).items():
  if isinstance(v,int):tokens[k]+=v
usage={'budget':Budget(S/'budget.sqlite3').report(),'model_http_status':dict(states),'model_tokens':dict(tokens),'reported_models':dict(models_reported),'cost_amount':None,'cost_note':'Exact gateway debit not retrieved; token usage and requests counted cumulatively, including aborted attempts. User explicitly lifted prior limits.'};(S/'resume-usage-summary.json').write_text(json.dumps(usage,indent=2))
text=['# 最终真实模型对话与执行证据','本次使用真实Qwen3.7-Plus与原One-API链路；设备为有状态软件模拟，记忆写入真实隔离管理API及数据库。','本记录不作为硬件物理动作的验收证明。','']
compact=['# 最终对话原文','模拟设备、隔离业务数据，真实主模型。','同一会话标识的多轮共享上下文和业务状态；标为独立用例的测试使用各自预置状态。不同会话之间的咖啡/绿茶、音量和卡片状态不能当作同一段连续对话。','']
for x in rows:
 block=['',f"## {x['case']['id']}",'','会话：'+str(x['case'].get('session') or ('独立用例 '+x['case']['id'])),'','**用户：** '+x['case']['query'],'','**智能体：** '+x.get('speech',''),'','核对：'+str(x['errors'] or '通过'),'']
 compact+=block
 text+=block+['```json',json.dumps({'call_results':x.get('outcome',{}).get('results'),'persisted_state':x.get('state'),'readback':x.get('readback'),'tts_events':x.get('events'),'assistant_history':x.get('assistant_history')},ensure_ascii=False,indent=2),'```']
(S/'resume-complete-dialogues.md').write_text('\n'.join(text));(S/'resume-dialogues-only.md').write_text('\n'.join(compact))
java=['src/main/java/xiaozhi/modules/personmemory/'+n for n in ['RecentArchiveService.java','PersonMemoryService.java','PersonMemoryController.java']]+[str(next((S/'manager-api/src/main/java').rglob('ConfigServiceImpl.java')).relative_to(S/'manager-api'))]
manifest={'python':f['source'],'java':{n:hashlib.sha256((S/'manager-api'/n).read_bytes()).hexdigest() for n in java},'jar_sha256':f['jar_sha256']};manifest['version']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:16];(S/'resume-source-manifest.json').write_text(json.dumps(manifest,indent=2))
with tarfile.open(S/'resume-source-only.tgz','w:gz') as t:
 for n in f['source']:t.add(S/'work'/n,arcname='python/'+n)
 for n in java:t.add(S/'manager-api'/n,arcname='java/'+n)
