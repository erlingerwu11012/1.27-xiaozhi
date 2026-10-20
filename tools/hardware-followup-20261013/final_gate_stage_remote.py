from pathlib import Path
import os,sys,json,hashlib,shutil,time,subprocess,ast
S=Path('/root/prjs/tmp/hardware-followup-20261013');R=Path('/root/prjs/releases/harness-followup-20261013');sys.path.insert(0,str(S))
from budget import Budget
b=Budget();charge=b.reserve('case','final-source-freeze-evidence-gate-and-candidate-entry')
try:
 rows=list(map(json.loads,(S/'final09-results.jsonl').read_text().splitlines()));assert len(rows)==181 and all(not r['errors'] for r in rows)
 groups={r['group'] for r in rows if r['group'].startswith('combo-')};assert len(groups)==30 and all(sum(r['group']==g for r in rows)>=5 for g in groups)
 assert sum(r['group'].startswith('single-') for r in rows)==30
 overlays={}
 for name in ['quality01','quality02','quality03','quality04','quality05','quality07']:
  for r in map(json.loads,(S/(name+'-results.jsonl')).read_text().splitlines()):
   if r.get('passed'):overlays[(r['group'],r['turn'])]={'source':name,'method':'recorded_context_replay' if 'result' in r else 'verified_result_reply_replay_no_business_redispatch','speech':r['speech']}
 assert len(overlays)==18
 expected={(f'combo-{i:02}',1) for i in range(24,30)}|{('combo-01',1),('combo-10',0),('combo-14',0),('combo-09',4),('combo-00',0),('single-16',0),('single-00',0),('combo-03',0)}|{(f'combo-{i:02}',1) for i in [17,18,20,21]}
 assert set(overlays)==expected and overlays[('single-00',0)]['source']=='quality05' and overlays[('combo-26',1)]['source']=='quality03'
 supplement=list(map(json.loads,(S/'supplement01-results.jsonl').read_text().splitlines()));assert len(supplement)==6 and all(r['passed'] for r in supplement)
 assert json.loads((S/'history-retry-evidence.json').read_text())['passed']
 latency=json.loads((S/'latency-comparison.json').read_text());assert latency['tool_gate'] and latency['audio_gate']
 for name in ['deterministic-05.log','ota-api-03.log','lifecycle-04.log','network-stream-02.log','confirmation-01.log','selection-03.log','ingress-01.log','quality-unit-01.log','weather-unit01.log','internal-id-unit01.log','greeting-unit03.log']:
  assert '\nOK' in (S/name).read_text(),name
 vision=json.loads((S/'vision-http-followup-results.json').read_text());vision=vision if isinstance(vision,list) else vision['records'];assert len(vision)==6 and [r['status'] for r in vision]==[401,403,200,200,403,200]
 assert json.loads((S/'predeploy-backup02/manifest.json').read_text())['restore_passed']
 assert json.loads((S/'api-package-evidence-05.json').read_text())['other_entries_identical']
 assert shutil.disk_usage('/').free>150*1024**2
 frozen={};updated=[]
 for p in (S/'work').rglob('*'):
  rel=p.relative_to(S/'work')
  if not p.is_file() or p.is_symlink() or any(x in {'__pycache__','logs','tmp','data','.git','test','models','build','target'} for x in rel.parts) or p.suffix not in {'.py','.txt','.yaml','.yml','.json'} or str(rel)=='config.yaml':continue
  if p.suffix=='.py':ast.parse(p.read_text(),filename=str(rel))
  digest=hashlib.sha256(p.read_bytes()).hexdigest();frozen[str(rel)]=digest;target=R/'runtime'/rel
  if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
   target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.final');shutil.copy2(p,temp);os.replace(temp,target);updated.append(str(rel))
 assert set(updated)<= {'core/utils/tool_harness/runtime.py','core/utils/tool_harness/reply_composer.py'},updated
 manifest=json.loads((R/'release-manifest.json').read_text());manifest.update(candidate_work_hashes=frozen,final_freeze_at=time.time(),last_updated_source=updated)
 (R/'release-manifest.json').write_text(json.dumps(manifest,indent=2));(S/'final-source-freeze.json').write_text(json.dumps(manifest,indent=2))
 review={'business_cases':181,'business_passed':181,'combo_count':30,'single_count':30,'reply_rechecks':18,'quality_reviewed_groups':30,'experience_clean_groups':29,'experience_pass_ratio':29/30,'minor_style_observation':'combo03 retains optional banter choice; no factual invention, user correction respected','source_versions_mixed':True,'same_version_full_rerun':False,'unaffected_evidence_reused_per_user_authorization':True,'replays_do_not_claim_business_redispatch':True,'overlays':[{'group':g,'turn':t,**v} for (g,t),v in sorted(overlays.items())],'supplemental_real_model_cases':6,'latency':latency,'production_changed':False,'firmware_flashed':False,'hardware_accepted':False,'budgets':b.report()}
 (S/'acceptance-final-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2))
 env=dict(os.environ,RELEASE_CHECK_NAME='followup02',RELEASE_ACCEPTANCE_CHARGE=str(charge))
 with (S/'final-candidate-check.log').open('x') as log:r=subprocess.run([sys.executable,str(S/'candidate_entry_remote.py')],env=env,cwd=S,stdout=log,stderr=subprocess.STDOUT)
 print((S/'final-candidate-check.log').read_text());assert r.returncode==0
 assert json.loads((S/'followup02-candidate-evidence.json').read_text())['passed']
 b.finish(charge,{'passed':True,'source_freeze':True,'business_cases':181,'reply_rechecks':18,'candidate_real_entry':True,'production_changed':False})
 print(json.dumps({'gate_passed':True,'updated_sources':updated,'budget':b.report(),'free_bytes':shutil.disk_usage('/').free},ensure_ascii=False))
except BaseException as exc:b.finish(charge,{'passed':False,'reason':str(exc)[:200]});raise
