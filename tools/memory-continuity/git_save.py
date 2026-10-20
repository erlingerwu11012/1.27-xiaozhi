"""Save only reviewed source/docs; no configs, archives, credentials or customer data."""
import sys,subprocess,json,re
from pathlib import Path
remote=len(sys.argv)>1 and sys.argv[1]=='remote'
root=Path('/root/prjs/xiaozhi-esp32-server') if remote else Path(__file__).resolve().parents[2]
if remote:
 names=list(json.loads(Path('/root/prjs/tmp/memory-continuity-release-20260930/manifest.json').read_text()))
 names+=['docs/MEMORY_CONTINUITY_IMPLEMENTATION_20260930.md','docs/BAILIAN_MEMORY_PRD_20260928.md']
else:
 names=[p.relative_to(root).as_posix() for p in (root/'tools/memory-continuity').rglob('*') if p.is_file() and p.suffix in {'.py','.json','.java','.sql','.yaml','.md'} and '__pycache__' not in p.parts]
 names+=['docs/MEMORY_CONTINUITY_IMPLEMENTATION_20260930.md','docs/BAILIAN_MEMORY_PRD_20260928.md']
for name in names:
 p=root/name;assert p.exists(),name
 text=p.read_text(encoding='utf-8')
 assert not re.search(r'^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text,re.M),name
 assert not re.search(r'sk-[A-Za-z0-9]{24,}',text),name
subprocess.run(['git','add','--',*names],cwd=root,check=True)
staged=subprocess.check_output(['git','diff','--cached','--name-only'],cwd=root,text=True).splitlines()
assert set(staged).issubset(set(names)),'unrelated_staged_files'
subprocess.run(['git','commit','-m','feat: ship 10k-token personal extraction, cross-wake continuity and 72h audio retention'],cwd=root,check=True,stdout=subprocess.DEVNULL)
tag='memory-continuity-20260930'
subprocess.run(['git','tag','-a',tag,'-m','Tested and deployed memory continuity: 10k user tokens, 50 turns, 72h audio; portraits off, physical checks pending'],cwd=root,check=True)
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
print(json.dumps({'commit':head,'tag':tag,'pushed':False,'source_files':len(staged)}))
