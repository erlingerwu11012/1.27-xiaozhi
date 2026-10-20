from pathlib import Path
import subprocess,json,re,collections
root=Path.cwd()
rows=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z']).decode().split('\0')
allowed=[];excluded=[]
secret=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|\bsk-[A-Za-z0-9_-]{20,}|(?i:Bearer )(?=[A-Za-z0-9_-]{28})[A-Za-z0-9_.-]+|(?i:(?:api_key|apikey|password|secret_key|access_token)\s*[=:]\s*[\"\x27])([A-Za-z0-9_/-]{24,})')
for n in filter(None,rows):
 p=root/n;reason=None
 if n.startswith('build-'):reason='build output'
 elif p.suffix.lower() in {'.tgz','.zip','.gz','.sqlite3','.db','.elf','.map'}:reason='generated archive/database'
 elif p.name in {'sdkconfig','config.yaml','runtime-config.json','device-config.json'} or 'private-backup' in n:reason='private configuration'
 elif p.suffix.lower() in {'.txt','.json','.jsonl'} and any(k in n.lower() for k in ['hardware-log','capture','serial']):reason='raw device capture'
 elif p.stat().st_size<20_000_000 and p.suffix.lower() not in {'.png','.jpg','.jpeg','.webp','.wav','.ogg','.mp3','.mp4'} and secret.search(p.read_bytes().replace(b'device-pairing-secret-not-enroll',b'DUMMY').replace(b'sk-abcdefghijklmnopqrstuvwxyz',b'DUMMY').replace(b'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaaaaaaabbbbbbbb.ccccccccdddddddd',b'DUMMY')):reason='credential-like content'
 (excluded if reason else allowed).append({'path':n,'reason':reason} if reason else n)
result={'allowed':allowed,'excluded':excluded};(root/'tools/mcp-prune-20261010/local-commit-inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'allowed':len(allowed),'excluded_counts':dict(collections.Counter(x['reason'] for x in excluded)),'review': [x for x in excluded if x['reason'] not in {'build output','generated archive/database'}]},ensure_ascii=False,indent=2))
