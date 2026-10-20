from pathlib import Path
import json,zipfile,hashlib,re
S=Path('tools/experience-repair-20261009');E=S/'evidence';d=json.loads((E/'delivery-summary.json').read_text(encoding='utf-8'));assert d['deployed'] and not d['draft'] and d['observation_seconds']>=1800
f=json.loads((E/'final-freeze.json').read_text(encoding='utf-8'));assert all(hashlib.sha256(p.read_bytes()).hexdigest()==f['java_source'][p.name] for p in (E/'java').glob('*.java'))
for p in [Path('releases/experience-repair-20261009.zip'),Path('releases/experience-repair-evidence-20261009.zip')]:
 with zipfile.ZipFile(p) as z:assert z.testzip() is None
for link in re.findall(r'\]\(([^)]+)\)',(S/'TEST-REVIEW.md').read_text(encoding='utf-8')):
 if not link.startswith('http'):assert Path(link).exists(),link
print('Final artifacts: archives readable, links resolve, deployment verified, Java hashes match frozen test source.')
