"""Commit explicit source and reviewed non-sensitive evidence paths only."""
import hashlib, json, shutil, subprocess
from pathlib import Path
REPO=Path('/root/prjs/xiaozhi-esp32-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
def git(*args):return subprocess.run(['git','-C',str(REPO),*args],check=True,capture_output=True,text=True).stdout
assert git('rev-parse','HEAD').strip()=='79e4ed56a6ddd418452bdcd88fecb7d0b296c544'
already_staged=set(git('diff','--cached','--name-only').splitlines())
receipt=json.loads((OUT/'deployment-receipt.json').read_text())
sources=['main/xiaozhi-server/'+name for name in (OUT/'changed-files.txt').read_text().splitlines()]
for path in sources:
    name=path.removeprefix('main/xiaozhi-server/')
    assert hashlib.sha256((REPO/path).read_bytes()).hexdigest()==receipt['files'][name]['after_sha256']
evidence=['regression.json','model-acceptance.json','model-failure-revalidation.json','style-revalidation.json',
          'latency-acceptance.json','compatibility-baseline.json','compatibility-regression.json',
          'live-chain-acceptance.json','asr-context-acceptance.json','hardware-acceptance.json',
          'pipeline-acceptance.json','deployment-receipt.json','production-verification.json']
def private_keys(obj):
    if isinstance(obj,dict):
        assert not {'api_key','password','secret','HW_BILLING_SERVICE_KEY','Authorization'} & set(obj),'private credential field'
        for value in obj.values():private_keys(value)
    elif isinstance(obj,list):
        for value in obj:private_keys(value)
paths=list(sources)
target=REPO/'docs/natural-dialogue-20261003';target.mkdir(parents=True,exist_ok=True)
for name in evidence:
    data=(OUT/name).read_bytes();private_keys(json.loads(data))
    path=target/name
    if path.exists():assert path.read_bytes()==data,'evidence concurrently changed: '+name
    else:path.write_bytes(data)
    paths.append(str(path.relative_to(REPO)))
report='docs/NATURAL_DIALOGUE_MCP_IMPLEMENTATION_REPORT_20261003.md'
if (REPO/report).exists():assert (REPO/report).read_bytes()==(OUT/Path(report).name).read_bytes()
else:shutil.copy2(OUT/Path(report).name,REPO/report)
paths.append(report)
assert already_staged <= set(paths),'another staged change exists'
# Only these reviewed JSON reports bypass the general runtime JSON ignore rule.
git('add','--',*sources,report)
git('add','-f','--',*[str((target/name).relative_to(REPO)) for name in evidence])
staged=git('diff','--cached','--name-only').splitlines()
assert set(staged)==set(paths),'unexpected staged file'
git('-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
    'diff','--cached','--check')
message='Improve natural dialogue and validate MCP actions before execution'
git('commit','-m',message)
commit=git('rev-parse','HEAD').strip()
assert not git('status','--porcelain','--untracked-files=no').strip()
(OUT/'commit-receipt.json').write_text(json.dumps({'commit':commit,'files':len(paths),'sensitive_files_committed':False},indent=2))
print(json.dumps({'commit':commit,'files':len(paths),'tracked_worktree_clean':True,'sensitive_files_committed':False}))
