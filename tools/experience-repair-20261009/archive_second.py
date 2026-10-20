from pathlib import Path
import json,time
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log']:
 p=S/n
 if p.exists():p.rename(S/('aborted-second-'+n))
(S/'aborted-second-note.json').write_text(json.dumps({'reason':'stopped when final tests exposed render/brightness goal collision, wrong relative volume and ordinal brightness; all original failures retained','time':time.time()}))
