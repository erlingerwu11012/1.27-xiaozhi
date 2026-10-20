import json,time
from pathlib import Path
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log']:
 p=S/n
 if p.exists():p.rename(S/('aborted-first-'+n))
(S/'aborted-first-note.json').write_text(json.dumps({'reason':'plain note negation, first read write goal, and note content extraction defects; stopped to save cost','time':time.time(),'kept_all_failures':True},indent=2))
