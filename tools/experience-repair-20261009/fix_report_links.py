from pathlib import Path
p=Path('tools/experience-repair-20261009/finalize_report.py');s=p.read_text(encoding='utf-8')
for n in ['FULL-CONVERSATIONS.md','ORIGINAL-FAILURES.md','tool-coverage.json','release-gate.json']:
 s=s.replace('(evidence/'+n+')',"({(E/'"+n+"').resolve().as_posix()})")
p.write_text(s,encoding='utf-8')
