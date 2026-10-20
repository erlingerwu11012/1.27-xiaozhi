"""Commit only explicit public sources and synthetic/authorized test evidence."""
import hashlib,json,re,shutil,subprocess,tarfile
from pathlib import Path
from urllib.request import urlopen
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005');REPO=Path('/root/prjs/xiaozhi-esp32-server')
receipt=json.loads((OUT/'deployment-receipt.json').read_text())
def git(*args):
 p=subprocess.run(['git','-C',str(REPO),*args],capture_output=True,text=True)
 assert p.returncode==0,'git_operation_failed'
 return p.stdout.strip()
assert git('rev-parse','HEAD')=='5419da5b9c8db490bf42efac9e21449d2d533f9b'
already_staged=set(git('diff','--cached','--name-only').splitlines())
sources=list(receipt['source_files'])
assert set(git('diff','--name-only').splitlines())<=set(sources)
for name,row in receipt['source_files'].items():assert hashlib.sha256((REPO/name).read_bytes()).hexdigest()==row['after']
assert json.loads((OUT/'production-acceptance.json').read_text())['actual_mcp_executions']==3
assert json.loads((OUT/'device-config-acceptance.json').read_text())['bill_state']=='settled'
index=(REPO/'main/manager-web/dist/index.html').read_text()
with urlopen('https://www.realecho.cn/',timeout=15) as response:public=response.read().decode()
app=re.search(r'src="(/js/app[^" ]+\.js)"',index).group(1)
assert app in public,'public_frontend_is_stale'
with urlopen('https://www.realecho.cn'+app,timeout=15) as response:
 assert hashlib.sha256(response.read()).hexdigest()==hashlib.sha256((REPO/'main/manager-web/dist'/app.lstrip('/')).read_bytes()).hexdigest()
(OUT/'public-verification.json').write_text(json.dumps({'public_index_matches_release':True,'public_app_bundle_matches_release':True,'url':'https://www.realecho.cn/','application_bundle':app},indent=2))
evidence=['regression.json','ui-component-tests.json','live-prompt-acceptance.json','final-acceptance.json','release-acceptance.json','tool-pipeline-acceptance.json','gateway-cloud-acceptance.json','production-mcp-proposals.json','production-acceptance.json','device-config-acceptance.json','deployment-receipt.json','public-verification.json']
def private_keys(obj):
 if isinstance(obj,dict):
  assert not {'api_key','password','secret','HW_BILLING_SERVICE_KEY','Authorization'}&set(obj),'private_field_in_evidence'
  for value in obj.values():private_keys(value)
 elif isinstance(obj,list):
  for value in obj:private_keys(value)
 elif isinstance(obj,str):assert not re.search(r'sk-[A-Za-z0-9]{20,}',obj),'credential_like_string'
docs=REPO/'docs/natural-dialogue-presets-20261005';docs.mkdir(parents=True,exist_ok=True)
paths=list(sources)
for name in evidence:
 data=(OUT/name).read_bytes();private_keys(json.loads(data));target=docs/name
 assert not target.exists() or target.read_bytes()==data,'existing_evidence_would_be_overwritten'
 target.write_bytes(data);paths.append(str(target.relative_to(REPO)))
summary=docs/'gateway-native-compatibility-failure.json'
summary.write_text(json.dumps({'model':'qwen3.8-flash','old_native_channel_http_status':400,'source':'captured isolated test terminal output','test':'TestQwen38RealAliRelayAndPaidLedger','operation':'native','resolved_with':'OpenAI-compatible channel; six real relay tests passed'},indent=2))
paths.append(str(summary.relative_to(REPO)))
report='docs/NATURAL_DIALOGUE_AND_PERSONA_PRESETS_20261005.md';shutil.copy2(OUT/Path(report).name,REPO/report);paths.append(report)
gate=json.loads((OUT/'release-plan.json').read_text())['gateway_files']
for name in gate:
 target=REPO/'tools/natural-dialogue-presets-20261005/gateway'/name
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(OUT/'gateway-candidate'/name,target);paths.append(str(target.relative_to(REPO)))
for name in ['live_prompt_acceptance.py','final_acceptance.py','release_acceptance.py','ui_component_tests.cjs','tool_pipeline_acceptance.py','gateway_cloud_acceptance.py','runtime_production_acceptance.py','device_config_acceptance.py','prepare_release.py','deploy_release.py','promote_mcp_patch.py']:
 target=REPO/'tools/natural-dialogue-presets-20261005'/name
 target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((OUT/name).read_bytes().rstrip(b'\r\n')+b'\n');paths.append(str(target.relative_to(REPO)))
ordinary=[p for p in paths if not p.endswith('.json')];reports=[p for p in paths if p.endswith('.json')]
assert already_staged<=set(paths),'unrelated_staged_files'
git('add','--',*ordinary);git('add','-f','--',*reports)
assert set(git('diff','--cached','--name-only').splitlines())==set(paths),'unexpected_staged_files'
git('-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol','diff','--cached','--check')
git('commit','-m','Add editable personality presets and improve natural dialogue with verified tool routing')
commit=git('rev-parse','HEAD');assert not git('status','--porcelain','--untracked-files=no')
result={'commit':commit,'public_files':len(paths),'sensitive_files_committed':False,'tracked_worktree_clean':True}
(OUT/'commit-receipt.json').write_text(json.dumps(result,indent=2))
with tarfile.open(OUT/'public-evidence.tar.gz','w:gz') as archive:
 for p in docs.iterdir():archive.add(p,arcname=p.name)
 archive.add(OUT/'commit-receipt.json',arcname='commit-receipt.json')
print(json.dumps(result))
