from pathlib import Path
import subprocess,json,hashlib,tarfile,shutil,os
repo=Path('/root/prjs/xiaozhi-esp32-server');stage=Path('/root/prjs/tmp/mcp-prune-20261010')
def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
tracked=git('diff','--name-only').splitlines();new=git('ls-files','--others','--exclude-standard','main').splitlines()
allowed=[n for n in new if (n.endswith(('.py','.java','.sql','.vue','.js')) and '/config/' not in n and '/resources/' not in n)]
private=[n for n in new if n not in allowed]
assert not git('diff','--cached','--name-only'),'existing staged changes'
(stage/'backup/pre-commit.patch').write_bytes(subprocess.check_output(['git','-C',str(repo),'diff','--binary']))
doc=repo/'docs/MCP_MAINTENANCE_RETIREMENT_20261010.md';doc.write_text('''# Six maintenance MCP endpoints retired

Firmware registration and server catalog/dispatch deny list remove self.get_system_info, self.reboot, self.screen.get_info, self.screen.set_render_mode, self.screen.set_render_options, self.screen.get_render_status.

Old firmware may still advertise them; server does not expose or dispatch them. Internal firmware reboot/render functionality remains. Firmware compilation and flashing were explicitly deferred.

The focused server test passed 63 checks without model calls. Previous uncommitted application fixes are included in this source checkpoint; private configuration and database backups are excluded.
''')
allowed.append(str(doc.relative_to(repo)))
checkfile=repo/'tools/mcp-prune-20261010/test_retired_tools.py';checkfile.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(stage/checkfile.name,checkfile);allowed.append(str(checkfile.relative_to(repo)))
with tarfile.open(stage/'backup/uncommitted-public-source.tgz','w:gz') as t:
 for n in tracked+allowed:t.add(repo/n,arcname=n,recursive=False)
git('add','--',*tracked,*allowed)
paths=git('diff','--cached','--name-only').splitlines();assert set(paths)==set(tracked+allowed)
# Reject real key material; fixture credentials in tests are reviewed separately.
import re
pat=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|\bsk-[A-Za-z0-9_-]{24,}')
for n in paths:
 data=(repo/n).read_bytes()
 if '/test/' not in n and '/tests/' not in n:assert not pat.search(data),'credential-like content in '+n
subprocess.run(['git','-C',str(repo),'commit','-m','Checkpoint dialogue, memory and device fixes; retire six maintenance MCP endpoints'],check=True,stdout=subprocess.DEVNULL)
result={'commit':git('rev-parse','HEAD'),'files':len(paths),'tracked_worktree_clean':not git('diff','--name-only'),'private_untracked_retained':len(private),'pushed':False}
(stage/'server-commit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
