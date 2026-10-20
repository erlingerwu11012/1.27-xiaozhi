import json,pathlib,subprocess,re,collections
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));app=next(x for x in apps if x['pm_id']==7)
print(json.dumps({'pm2_id':7,'pid':app['pid'],'status':app['pm2_env']['status'],'restarts':app['pm2_env'].get('restart_time')}))
for kind in ['pm_out_log_path','pm_err_log_path']:
 p=pathlib.Path(app['pm2_env'][kind]);size=p.stat().st_size
 with p.open('rb') as f:f.seek(max(0,size-8000000));lines=f.read().decode(errors='replace').splitlines()
 selected=[x for x in lines if '261009 00:14:' in x and any(v in x for v in ['WebSocket close','连接资源已释放','超时检查','harness.','Traceback','-ERROR-','-WARNING-','-WARN-'])]
 # Metadata only; avoid configuration dumps and identities.
 for x in selected[-35:]:
  x=re.sub(r'"(?:account_id|user_id|agent_id)"\s*:\s*"[^"]*"','"private_id":"[redacted]"',x)
  print(kind,x)
for name in ['error.log','access.log']:
 p=pathlib.Path('/var/log/nginx')/name
 with p.open('rb') as f:f.seek(max(0,p.stat().st_size-8000000));lines=f.read().decode(errors='replace').splitlines()
 selected=[x for x in lines if ('2026/10/09 00:14:' in x or '09/Oct/2026:00:14:' in x) and ('xiaozhi' in x or 'upstream' in x or 'timed out' in x)]
 print('nginx_'+name,json.dumps({'matching_lines':len(selected),'lines':[re.sub(r'(token|key|auth)=[^&\s"]+',r'\1=[redacted]',x) for x in selected[-20:]]},ensure_ascii=False))
