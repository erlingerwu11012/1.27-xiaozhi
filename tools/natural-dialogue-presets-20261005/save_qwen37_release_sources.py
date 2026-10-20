import hashlib,json,shutil,subprocess
from pathlib import Path
out=Path('/root/prjs/tmp/natural-dialogue-presets-20261005');prod=Path('/root/prjs/xiaozhi-esp32-server')
receipt=json.loads((out/'qwen37-official-deployment-20261007.json').read_text())
assert receipt['deployed'] and json.loads((out/'qwen37-production-mcp-20261007.json').read_text())['success']
def git(*args):return subprocess.check_output(['git','-C',str(prod),*args],text=True).strip()
staged=set(git('diff','--cached','--name-only').splitlines())
names=[]
for key,record in receipt['source_files'].items():
 kind,name=key.split(':',1)
 if kind=='gateway':continue
 rel=('main/xiaozhi-server/' if kind=='python' else 'main/manager-api/')+name
 assert hashlib.sha256((prod/rel).read_bytes()).hexdigest()==record['after']
 names.append(rel)
docroot='docs/natural-dialogue-presets-20261005/'
for name in ['QWEN37_OFFICIAL_DEPLOYMENT_20261007.md','qwen37-official-deployment-20261007.json','qwen37-production-billing-audit-20261007.json','qwen37-production-mcp-20261007.json']:
 dest=prod/docroot/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(out/name,dest);names.append(docroot+name)
# Gateway source resides outside Git: preserve this release's small, non-secret
# source snapshot inside the product repository for reproducible future builds.
gateway=Path('/root/prjs/one-api-bailian');prefix='tools/one-api-qwen37-source-20261007/'
for name in ['hardwarebilling/pricing.go','relay/controller/hardware_billing.go','relay/billing/ratio/model.go','hardwarebilling/qwen37_price_test.go','relay/controller/qwen37_cloud_test.go']:
 dest=prod/prefix/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(gateway/name,dest);names.append(prefix+name)
assert staged.issubset(set(names)),'unrelated_staged_changes_present'
git('add','--',*[n for n in names if not n.endswith('.json')])
# Global *.json rule also covers these reviewed, credential-free receipts.
git('add','-f','--',*[n for n in names if n.endswith('.json')])
assert set(git('diff','--cached','--name-only').splitlines())==set(names)
git('commit','-m','Deploy official Qwen3.7 Plus with verified tool policy and gateway billing')
print(json.dumps({'commit':git('rev-parse','HEAD'),'committed_files':len(names),'excluded_existing_wakeup_audio':True,'excluded_secrets_and_database_backups':True}))
