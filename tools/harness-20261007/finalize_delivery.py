import datetime,hashlib,json,os,subprocess,zipfile
from pathlib import Path
from zoneinfo import ZoneInfo
from rollout import STATE,RELEASE,STAGE,observe_metadata,pmid,health
import asyncio
s=json.loads(STATE.read_text());assert s['phase']=='deployed_verified','observation_not_complete'
o=json.loads((RELEASE/'observation.json').read_text());assert o['records'] and all(x['passed'] for x in o['records'])
assert s['observation_finished_at']-s['deployed_at']>=1800
checks=asyncio.run(health(internal_port=8006,public=True));assert all(x['passed'] for x in checks)
subprocess.run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',str(STAGE/'audit_live.py')],check=True,capture_output=True)
a=json.loads((STAGE/'live-readonly-audit.json').read_text());assert a['model']=='qwen3.7-plus' and float(a['temperature'])==.4 and a['hardware_billing'] and a['persona_unchanged'] and a['gateway_config_unchanged'] and a['official_provider_selection_unchanged']
p=pmid(s['new_pm2_id']);assert p['pm2_env']['status']=='online' and p['pm2_env'].get('restart_time',0)==0
meta=observe_metadata(s);assert meta['installed_source_matches'] and not meta.get('duplicate_dispatch_groups',0)
fmt=lambda t:datetime.datetime.fromtimestamp(t,ZoneInfo('Asia/Shanghai')).isoformat()
d={'phase':s['phase'],'domain':'https://www.realecho.cn','code_hash':s['gate']['code_hash'],'deployed_at':fmt(s['deployed_at']),'observation_finished_at':fmt(s['observation_finished_at']),'observation_seconds':round(s['observation_finished_at']-s['deployed_at']),'observation_checks':s['observation_checks'],'all_observation_checks_passed':True,'formal_health':checks,'process_status':p['pm2_env']['status'],'process_restarts':p['pm2_env'].get('restart_time',0),'model':a['model'],'temperature':a['temperature'],'thinking':False,'hardware_billing':a['hardware_billing'],'persona_unchanged':a['persona_unchanged'],'gateway_config_unchanged':a['gateway_config_unchanged'],'gateway_url':a['gateway_url'],'official_provider_selection_unchanged':a['official_provider_selection_unchanged'],'metadata':meta,'hardware_validation':False,'rollback_ledger_retained':True,'test_additional_model_requests':990,'test_total_records_since_cap':1841,'live_hardware_operations_observed':bool(meta.get('operation_states'))}
out=STAGE/'delivery';(out/'deployment-status.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))
text=(out/'README.md').read_text();text=text.replace('正式域名：www.realecho.cn。',f"正式域名：www.realecho.cn。已于 {d['deployed_at']} 上线；{d['observation_finished_at']} 完成30分钟观察，{d['observation_checks']}轮全部通过、重启0次。")
(out/'README.md').write_text(text)
(out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n' for f in sorted(out.iterdir()) if f.is_file() and f.name!='SHA256SUMS.txt'))
archive=STAGE/'harness-delivery-20261008.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
 for f in sorted(out.iterdir()):
  if f.is_file():z.write(f,f.name)
os.chmod(archive,0o600)
print(json.dumps(d,ensure_ascii=False));print(json.dumps({'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))
