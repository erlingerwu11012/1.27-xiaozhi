"""Overlay verified application files and configure alternate serving ports."""
from pathlib import Path
import hashlib,json,os,signal,shutil
S=Path(__file__).parent;R=Path('/root/prjs/releases/harness-stream-20261012')
freeze=json.loads((S/'final27-frozen.json').read_text())
inventory=json.loads((S/'release-preflight-v2.json').read_text())
for name in inventory['changed_source']:
 if name.startswith('test/'):continue
 source=S/'work'/name
 assert hashlib.sha256(source.read_bytes()).hexdigest()==freeze['files']['work/'+name]
 shutil.copy2(source,R/'runtime'/name)
shutil.copy2(S/'work/agent-base-prompt-v2.txt',R/'runtime/agent-base-prompt-v2.txt')
wrapper=(R/'serve.py').read_text()
if 'XIAOZHI_RELEASE_ALTERNATE_PORTS' not in wrapper:
 wrapper=wrapper.replace('candidate=os.environ.get("XIAOZHI_RELEASE_CANDIDATE")=="1"','candidate=os.environ.get("XIAOZHI_RELEASE_CANDIDATE")=="1"\nalternate=candidate or os.environ.get("XIAOZHI_RELEASE_ALTERNATE_PORTS")=="1"')
 wrapper=wrapper.replace('8170 if candidate else 8070','8170 if alternate else 8070').replace('8173 if candidate else 8073','8173 if alternate else 8073').replace('8176 if candidate else 8076','8176 if alternate else 8076')
 wrapper=wrapper.replace(' r=original(c);r["server"]=', ''' if candidate:
  c=dict(c);c["manager-api"]=dict(c.get("manager-api") or {},url="http://127.0.0.1:18002/xiaozhi",secret=Path("/root/prjs/tmp/harness-stream-20261011/api-test-secret").read_text(),max_retries=0)
  c["server"]=dict(c.get("server") or {},auth_key=c["manager-api"]["secret"],auth={"enabled":True,"allowed_devices":[]})
 r=original(c);r["server"]=''' )
 (R/'serve.py').write_text(wrapper)
assert 'alternate' in wrapper and 'if candidate:' in wrapper
pid=62166
path=Path('/proc')/str(pid)
if path.exists():
 assert str(R/'serve.py').encode() in (path/'cmdline').read_bytes()
 assert b'XIAOZHI_RELEASE_CANDIDATE=1' in (path/'environ').read_bytes().split(b'\0')
 os.kill(pid,signal.SIGTERM)
manifest={'business_source_freeze':'final27','api_package':'memory-api-package26.json','wrapper_sha256':hashlib.sha256((R/'serve.py').read_bytes()).hexdigest(),'prompt_sha256':hashlib.sha256((R/'runtime/agent-base-prompt-v2.txt').read_bytes()).hexdigest(),'alternate_ports':[8170,8173,8176],'formal_ledger_preserved':True,'isolated_candidate_uses_isolated_api':True,'production_modified':False}
(S/'release27-stage.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest))
