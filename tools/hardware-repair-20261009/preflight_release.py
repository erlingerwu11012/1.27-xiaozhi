from pathlib import Path
import importlib.util,json,socket,tarfile,hashlib,asyncio
S=Path(__file__).parent;spec=importlib.util.spec_from_file_location('candidate_release',S/'release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
result={'ports_free':{},'baseline_source_matches':True,'redis_connected':False}
for n,p in m.PORTS.items():
 with socket.socket() as s:result['ports_free'][n]=s.connect_ex(('127.0.0.1',p))!=0
with tarfile.open(S/'baseline/runtime.tgz') as t:
 for n in json.loads((S/'changed-files.json').read_text(encoding='utf-8-sig')):
  member=next((x for x in t.getmembers() if x.name=='./'+n),None);actual=Path('/root/prjs/releases/experience-repair-20261009/runtime')/n
  if member is None:
   if actual.exists():result['baseline_source_matches']=False
  elif t.extractfile(member).read()!=actual.read_bytes():result['baseline_source_matches']=False
r=m.redis_client();result['redis_connected']=bool(r.ping());value=r.hget('sys:params','server.voiceprint_similarity_threshold');result['cached_threshold_value_present']=value is not None
result['production_health']=asyncio.run(m.old.health(internal=8006,public=True));result['passed']=all(result['ports_free'].values()) and result['baseline_source_matches'] and result['redis_connected'] and all(x['passed'] for x in result['production_health']);(S/'resume-deploy-preflight.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));assert result['passed']
