from pathlib import Path
import json,time
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log']:
 p=S/n
 if p.exists():p.rename(S/('aborted-third-'+n))
(S/'aborted-third-note.json').write_text(json.dumps({'reason':'current-card semantics, raw Python error speech, conversation state failures; all failures preserved before latest fixes','time':time.time(),'budget_expansion_authorized':True},indent=2))
