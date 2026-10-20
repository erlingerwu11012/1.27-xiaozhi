from pathlib import Path
import yaml,json,subprocess
S=Path(__file__).parent
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));a=next(x for x in apps if x['name']=='voiceprint-api');cwd=Path(a['pm2_env']['pm_cwd']);cfg=yaml.safe_load((cwd/'data/.voiceprint.yaml').read_text());value=float((cfg.get('voiceprint') or {}).get('similarity_threshold',.2))
r={'backend_minimum_threshold':value,'allows_client_threshold_0_3':value<=.3,'process_online':a['pm2_env']['status']=='online'};(S/'voice-backend-threshold.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));assert r['allows_client_threshold_0_3']
