from pathlib import Path
import importlib.util,json,os,signal,hashlib,subprocess,time,shutil
stage=Path('/root/prjs/tmp/mcp-prune-20261010');rel=Path('/root/prjs/releases/mcp-prune-20261010');root=Path('/root/prjs/xiaozhi-esp32-server')
spec=importlib.util.spec_from_file_location('release_health','/root/prjs/releases/hardware-repair-20261009/release.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
state=json.loads((rel/'deployment.json').read_text());health=old.old.ready(ws=8070,http=8073,internal=8076,manager=18005,public=True)
a=old.app(state['new_pm_id']);assert a['pm2_env']['status']=='online';assert a['pm2_env']['pm_exec_path']==str(rel/'serve.py')
original=json.loads((rel/'process-private.json').read_text())['apps'][0]['env'];current=old.env_of(a)
keys=['HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN'];assert all(current.get(k)==original.get(k) for k in keys),'billing environment drift'
for n,dest in [('retired_tools.py','core/providers/tools/retired_tools.py'),('unified_tool_manager.py','core/providers/tools/unified_tool_manager.py'),('mcp_handler.py','core/providers/tools/device_mcp/mcp_handler.py')]:
 assert (root/'main/xiaozhi-server'/dest).read_bytes()==(rel/'runtime'/dest).read_bytes()
# Retire only the exact old serving process after the public entry is healthy.
pid=state['old_listener_pid'];cmd=Path('/proc',str(pid),'cmdline')
if cmd.exists():
 assert cmd.read_bytes().split(b'\0')[:3]==[old.PY.encode(),b'/root/prjs/releases/hardware-repair-20261009/release.py',b'serve']
 os.kill(pid,signal.SIGTERM)
subprocess.run(['pm2','save'],check=True,capture_output=True)
state.update(phase='verified',verified_at=time.time(),health=health,billing_environment_unchanged=True,old_listener_stopped=True)
(rel/'deployment.json').write_text(json.dumps(state,indent=2));(stage/'deployment.json').write_text(json.dumps(state,indent=2))
repo_tools=root/'tools/mcp-prune-20261010';repo_tools.mkdir(exist_ok=True,parents=True)
public=['test_retired_tools.py','deploy_server.py','cleanup_server.py','test-results.json','deployment.json','cleanup.json']
for n in public:shutil.copy2(stage/n,repo_tools/n)
subprocess.run(['git','-C',str(root),'add','-f','--',*[str((repo_tools/n).relative_to(root)) for n in public]],check=True)
subprocess.run(['git','-C',str(root),'commit','-m','Record maintenance-tool retirement checks, rollout and disk cleanup'],check=True,stdout=subprocess.DEVNULL)
commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
result=json.loads((stage/'server-commit.json').read_text());result['final_commit']=commit;result['tracked_worktree_clean']=not subprocess.check_output(['git','-C',str(root),'diff','--name-only'],text=True).strip();result['remaining_untracked']=len(subprocess.check_output(['git','-C',str(root),'ls-files','--others','--exclude-standard'],text=True).splitlines());(stage/'server-commit.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'commit':commit,'health_passed':all(x['passed'] for x in health),'billing_unchanged':True,'tracked_clean':result['tracked_worktree_clean'],'remaining_untracked_private':result['remaining_untracked']}))
