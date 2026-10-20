from pathlib import Path
import json,importlib.util,hashlib,subprocess
S=Path(__file__).parent;spec=importlib.util.spec_from_file_location('oldrelease','/root/prjs/releases/experience-repair-20261009/release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
a=m.apps();out={'pm2':[{k:x.get(k) for k in ['pm_id','name','pid']}|{'script':x['pm2_env']['pm_exec_path'],'args':x['pm2_env'].get('args'),'status':x['pm2_env']['status']} for x in a if x['name'] in ['xiaozhi-server','manager-api']]}
with m.db() as db:
 with db.cursor() as c:
  c.execute('SHOW COLUMNS FROM sys_params');out['params_columns']=[x[0] for x in c.fetchall()]
  c.execute("SELECT param_code,param_value FROM sys_params WHERE param_code='server.voiceprint_similarity_threshold'");out['voice_threshold']=c.fetchall()
  c.execute('SHOW COLUMNS FROM ai_person_material');out['material_columns']=[x[0] for x in c.fetchall()]
(S/'deployment-readonly-context.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
