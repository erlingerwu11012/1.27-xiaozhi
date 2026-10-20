"""Grade complete frozen evidence; preserve failures and pending phases."""
import collections,hashlib,json,math,statistics,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).parent.resolve()
sys.path.insert(0,str(root))
import bootstrap
from core.utils.tool_harness.contracts import contract
from core.utils.tool_harness.registry import manifest
from test_support import SimulationManager
pack=json.loads((root/'pack.json').read_text())
holdout=json.loads((root/'holdout.json').read_text())
def read(name):
    p=root/name
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
def pct(rows):return round(100*sum(r['passed'] for r in rows)/len(rows),4) if rows else None
def p95(values):return round(sorted(values)[max(0,math.ceil(len(values)*.95)-1)],2) if values else None
# Cost-limited incremental release evidence. No model requests in this postprocessor.
import copy
stage=root.parent
base=stage/'frozen-20261008-budget-final';micro=stage/'frozen-20261008-budget-live'
def rows_at(path):return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
old=rows_at(base/'budget-results.jsonl');delta=read('budget-results.jsonl');live=rows_at(micro/'budget-results.jsonl');replay=read('offline-replay.jsonl')
selected=set(json.loads((root/'budget-plan.json').read_text())['replaces_single_tools'])
oldmap={(r['suite'],r['id'],r['repeat']):r for r in old if r['chain']=='candidate'}
livemap={(r['suite'],r['id'],r['repeat']):r for r in live}
effective=[]
for r in replay:
 key=(r['suite'],r['id'],r['repeat']);source=copy.deepcopy(oldmap[key])
 if r['needs_live']:
  assert key in livemap,'missing_live_replay_evidence'
  source=copy.deepcopy(livemap[key]);source['provenance']='current-source-real-model'
 else:
  assert r['network_requests']==0 and r['passed']
  source['turns']=r['turns'];source['outcome']=r['turns'][-1]['outcome'];source['calls']=sum([t['calls'] for t in r['turns']],[]);source['passed']=r['passed']
  source['provenance']='old-source-real-model-decisions-replayed-on-current-source'
  source['latency_provenance']='original-real-model-run-not-replay-time'
 effective.append(source)
for r in delta:
 r=copy.deepcopy(r);r['provenance']='current-source-real-model';effective.append(r)
baselines=[r for r in old if r['chain']=='baseline']
files={name:[r for r in effective+baselines if r['suite']==name] for name in ['single','complex','holdout']}
expected={'single':631,'complex':60,'holdout':74}
manifest_hash=hashlib.sha256(json.dumps(json.loads((root/'candidate-manifest.json').read_text()),sort_keys=True).encode()).hexdigest()
report={'code_hash':manifest_hash,'pack_hash':pack['sha256'],'model':'qwen3.7-plus','temperature':.4,'thinking':False,'billing_gateway':True,'hardware':False,'expected_rows':expected,'actual_rows':{s:len(v) for s,v in files.items()},'chains':{}}
allrows=sum(files.values(),[])
for chain in ['baseline','candidate']:
    single=[r for r in files['single'] if r['chain']==chain]
    pos=[r for r in single if r['group']!='negative'];neg=[r for r in single if r['group']=='negative']
    tools=sorted(set(r['tool'] for r in pack['cases']))
    pertool={name:{'n':len(a:=[r for r in pos if r['expected_tool']==name]),'passed':sum(r['passed'] for r in a),'rate':pct(a)} for name in tools}
    common=[r for r in pos if r['expected_tool'] in pack['common']]
    phase=[]
    for r in pos:
        for result in r.get('outcome',{}).get('results',[]):
            if result['tool']==r['expected_tool'] and result['state']=='accepted':phase.append({'id':r['id'],'repeat':r['repeat'],'tool':result['tool'],'reply':result['reply']})
    failures=[r for r in allrows if r['chain']==chain and not r['passed']]
    apierrors=[r for r in allrows if r['chain']==chain and any(e.get('error_kind')=='api' for e in r.get('events',[]))]
    report['chains'][chain]={'single_positive_n':len(pos),'single_positive_passed':sum(r['passed'] for r in pos),'protocol_handling_rate':pct(pos),'common_n':len(common),'common_passed':sum(r['passed'] for r in common),'common_rate':pct(common),'negative_n':len(neg),'negative_passed':sum(r['passed'] for r in neg),'negative_rate':pct(neg),'per_tool':pertool,'complex_n':len(c:=[r for r in files['complex'] if r['chain']==chain]),'complex_passed':sum(r['passed'] for r in c),'holdout_n':len(h:=[r for r in files['holdout'] if r['chain']==chain]),'holdout_passed':sum(r['passed'] for r in h),'accepted_only_n':len(phase),'accepted_only_by_tool':dict(collections.Counter(p['tool'] for p in phase)),'accepted_is_not_completion':True,'verified_target_completed_n':sum(r['passed'] and any(x['tool']==r['expected_tool'] and x['state']=='completed' for x in r.get('outcome',{}).get('results',[])) for r in pos),'api_error_rows':len(apierrors),'failure_ids':[{'id':r['id'],'repeat':r['repeat'],'group':r['group']} for r in failures],'overall_single_p95_ms':p95([r['elapsed_ms'] for r in pos]),'single_model_requests':sum(r.get('outcome',{}).get('model_calls',0) for r in pos)}
# Compare matching cases; necessary tool dependencies and corrections separately.
paired={s:{(r['id'],r['repeat']):r for r in files['single'] if r['chain']==s and r['group']!='negative'} for s in ['baseline','candidate']}
normal=[];dependency=[];repaired=[]
for key in paired['baseline'].keys()&paired['candidate'].keys():
    b,c=paired['baseline'][key],paired['candidate'][key]
    pair={'id':key[0],'repeat':key[1],'baseline_ms':b['elapsed_ms'],'candidate_ms':c['elapsed_ms'],'baseline_calls':b.get('outcome',{}).get('model_calls',0),'candidate_calls':c.get('outcome',{}).get('model_calls',0)}
    if c.get('outcome',{}).get('repairs'):repaired.append(pair)
    elif contract(c['expected_tool']).prerequisites or any(e.get('decision',{}).get('steps') and any(x.get('relative') or x.get('extreme') for x in e['decision']['steps']) for e in c.get('events',[]) if isinstance(e.get('decision'),dict)):dependency.append(pair)
    else:normal.append(pair)
lat={}
for name,pairs in [('normal',normal),('dependencies',dependency),('corrections',repaired)]:
    bp=p95([p['baseline_ms'] for p in pairs]);cp=p95([p['candidate_ms'] for p in pairs])
    lat[name]={'n':len(pairs),'baseline_p95_ms':bp,'candidate_p95_ms':cp,'p95_ratio':round(cp/bp,4) if bp and cp else None,'baseline_calls':sum(p['baseline_calls'] for p in pairs),'candidate_calls':sum(p['candidate_calls'] for p in pairs),'more_requests_cases':[p for p in pairs if p['candidate_calls']>p['baseline_calls']]}
report['latency']=lat
report['complete_evidence']=all(report['actual_rows'][s]==n for s,n in expected.items())
report['postprocessor_hash']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
frozen_hashes=json.loads((root/'frozen-hashes.json').read_text())
report['frozen_files_intact']=all((root/n).is_file() and hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in frozen_hashes.items())
report['unique_rows']=len(allrows)==len({(r['chain'],suite,r['id'],r['repeat']) for suite,rows in files.items() for r in rows})
report['version_matches']=all(r['code_hash']==manifest_hash and r['pack_hash']==pack['sha256'] for r in delta+live) and all(r['pack_hash']==pack['sha256'] for r in old)
report['catalog']=manifest(SimulationManager())
report['catalog_eligible']=sum(r['availability']=='available' for r in report['catalog'])
report['coverage_eligible_matches']=set(r['name'] for r in report['catalog'] if r['availability']=='available')==set(r['tool'] for r in pack['cases'])
# Fully completed goals are deliberately distinct from correctly handled queued requests.
# This report alone must not authorize deployment or treat accepted as completed.
report['accepted_phase_policy']={'user_confirmed':True,'criterion':'Correct dispatch and truthful accepted-stage report; never final completion.'}
candidate_rows=[r for r in allrows if r['chain']=='candidate']
positive_rows=[r for r in candidate_rows if r.get('group')!='negative']
safety={'nonrequested_write_turns':[],'duplicate_write_turns':[],'receipt_output_mismatch_turns':[],'unreviewed_chat_claims':[]}
from core.utils.tool_harness.runtime import Harness
for r in candidate_rows:
    for ti,t in enumerate(r.get('turns',[])):
        writes=[c for c in t['calls'] if contract(c['tool']).write]
        if r.get('group')=='negative':allowed=set()
        elif r.get('group') in {'complex','holdout'}:allowed={e['tool'] for e in t.get('expected') or [] if contract(e['tool']).write}
        else:allowed={r['expected_tool']}|set(contract(r['expected_tool']).prerequisites)
        ident={'id':r['id'],'repeat':r['repeat'],'turn':ti}
        if any(c['tool'] not in allowed for c in writes):safety['nonrequested_write_turns'].append(ident)
        fingerprints=[json.dumps([c['tool'],c['arguments']],sort_keys=True,ensure_ascii=False) for c in writes]
        if len(fingerprints)!=len(set(fingerprints)):safety['duplicate_write_turns'].append(ident)
        out=t['outcome'];results=out.get('results',[])
        if results and not out.get('interrupted') and out['mode'] not in {'chat','clarify'}:
            meaningful=[x for x in results if not x.get('intermediate') or x['state']!='completed']
            reply=''.join(x['reply'] for x in meaningful) or '这次没有执行成功，需要确认操作目标或参数。'
            if any(x['state']!='completed' for x in results):reply+='未确认的操作不会自动重复执行。'
            if out['reply']!=reply:safety['receipt_output_mismatch_turns'].append(ident)
        elif not results and Harness.claims_action(out['reply']):safety['unreviewed_chat_claims'].append(ident)
report['safety_evidence']=safety
legal=[r for r in positive_rows if r.get('expected_tool') or any(t.get('expected') for t in r.get('turns',[]))]
nonoperations=[r for r in positive_rows if r not in legal]
report['positive_all_suites']={'n':len(legal),'passed':sum(r['passed'] for r in legal),'rate':pct(legal),'excludes_chat_negation_missing_parameters':True}
report['nonoperation_scenarios']={'n':len(nonoperations),'passed':sum(r['passed'] for r in nonoperations),'rate':pct(nonoperations)}
common_all=[r for r in legal if r.get('expected_tool') in pack['common'] or any(e['tool'] in pack['common'] for t in r.get('turns',[]) for e in t.get('expected') or [])]
report['common_all_suites']={'n':len(common_all),'passed':sum(r['passed'] for r in common_all),'rate':pct(common_all)}
recall_rows=[r for r in candidate_rows if r.get('expected_tool') and r.get('group')!='negative']
recalled=[r for r in recall_rows if r['expected_tool'] in set(r.get('schema_tools_shown',[]))|{c['tool'] for c in r.get('calls',[])}]
report['final_required_tool_recall']={'n':len(recall_rows),'recalled':len(recalled),'rate':round(100*len(recalled)/len(recall_rows),4) if recall_rows else None}
from rollout import validate_frozen
frozen_proof={str(d.name):validate_frozen(d)[0] for d in [base,root,micro]}
assert frozen_proof[root.name]==frozen_proof[micro.name]==manifest_hash
assert len(old)==749 and len(delta)==172 and len(live)==2 and len(replay)==550
assert len({(r['suite'],r['id'],r['repeat']) for r in effective})==722
for directory,rows in [(base,old),(root,delta),(micro,live)]:
 tasks=json.loads((directory/'budget-plan.json').read_text())['tasks']
 assert {(t['chain'],t['suite'],t['row']['id'],t['repeat']) for t in tasks}=={(r['chain'],r['suite'],r['id'],r['repeat']) for r in rows}
 assert all(r['code_hash']==frozen_proof[directory.name] for r in rows)
assert all(r['passed'] for r in delta+live)
replaced=[r for r in old if r['chain']=='candidate' and r['suite']=='single' and r['expected_tool'] in selected]
assert {(r['id'],r['repeat']) for r in replaced}=={(r['id'],r['repeat']) for r in delta if r['suite']=='single'}
report['provenance']={'real_model_current_source_rows':len(delta)+len(live),'recorded_decision_replay_current_source_rows':len(replay)-len(live),'effective_candidate_rows':len(effective),'matched_baseline_rows':len(baselines),'frozen_sources':frozen_proof,'final_source_entire_suite_rerun':False,'hardware':False,'limitation':'Incremental execution evidence; replay does not re-test model semantic response to revised prompts. Future natural-language accuracy is not guaranteed.'}
report['budget']=json.loads((micro/'budget-run-summary.json').read_text())['budget']
report['jobs']=json.loads((root/'budget-jobs-results.json').read_text())
report['previous_failures']=[{'id':r['id'],'chain':r['chain'],'suite':r['suite'],'expected_tool':r.get('expected_tool'),'turns':r.get('turns')} for r in old if not r['passed']]
report['oracle_corrections']=['Verified intermediate state read is allowed for absolute setting; retained in normal-operation latency.','Exact anchored reminder equivalent: 该 + expected content + 了. Actual production text/time parser is used. Original failures are retained.']
report['evidence_hashes']={str(path.relative_to(stage)):hashlib.sha256(path.read_bytes()).hexdigest() for path in [base/'budget-results.jsonl',root/'budget-results.jsonl',micro/'budget-results.jsonl',root/'offline-replay.jsonl',root/'budget-jobs-results.json',root/'full-message-evidence.json']}
report['deployment_authorized_by_report']=False
(stage/'budget-release-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
(stage/'budget-tool-coverage.json').write_text(json.dumps(report['catalog'],ensure_ascii=False,indent=2),encoding='utf8')
transcript=['# 完整模拟验收对话','实际模型：Qwen3.7-Plus，非思考，温度0.4，统一计费网关。设备与业务写入全部模拟；这不是实机记录。','排队、接收与完成分别记录；失败样本全部保留。']
for suite,rows in files.items():
    for r in rows:
        transcript.extend(['',f"## {suite} / {r['chain']} / {r['id']} / 第{r['repeat']+1}次",f"证据来源：{r.get('provenance','original-baseline')}；测试判定：{'通过' if r['passed'] else '失败'}；总耗时 {r['elapsed_ms']} ms"])
        for turn in r.get('turns',[]):
            transcript.extend(['', '用户：'+turn['user'],'回复：'+turn['outcome']['reply'],'调用、回执和状态：','```json',json.dumps({'calls':turn['calls'],'results':turn['outcome']['results'],'error':turn['outcome'].get('error'),'events':turn.get('events',[])},ensure_ascii=False,indent=2),'```'])
(stage/'budget-conversations.md').write_text('\n'.join(transcript),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k not in {'catalog','chains','previous_failures','evidence_hashes'}},ensure_ascii=False))
for chain,v in report['chains'].items():print(json.dumps({'chain':chain,**{k:a for k,a in v.items() if k not in {'per_tool','failure_ids'}}},ensure_ascii=False))
