import pathlib,difflib,json,subprocess,time,os
p=pathlib.Path('/root/prjs/releases/tool-harness-20261008/backup');root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
for n in ['core/handle/receiveAudioHandle.py','config/config_loader.py','core/connection.py']:
 old=(p/'source'/n).read_text();new=(root/n).read_text();diff=list(difflib.unified_diff(old.splitlines(),new.splitlines(),fromfile='before/'+n,tofile='after/'+n,n=3));print('\n'.join(diff))
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));a=next(x for x in apps if x['pm_id']==7)
print(json.dumps({'cpu_percent':a['monit']['cpu'],'rss_bytes':a['monit']['memory'],'loadavg':os.getloadavg(),'restarts':a['pm2_env'].get('restart_time'),'other_harness_workers':subprocess.check_output(['pgrep','-af','run_budget|run_compare|run_budget_worker|launch_candidate.py'],text=True).splitlines() if subprocess.run(['pgrep','-f','run_budget|run_compare|run_budget_worker|launch_candidate.py'],capture_output=True).returncode==0 else []}))
