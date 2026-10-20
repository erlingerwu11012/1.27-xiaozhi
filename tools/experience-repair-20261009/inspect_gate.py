from pathlib import Path
import json,xml.etree.ElementTree as ET
S=Path(__file__).parent
for n in ['http-api-results.json','real-tts-results.json','vision-http-results.json','ws-boundary-results.json','relative-canonical-results.json','lifecycle-summary.json','low-cost-summary.json','live-query-note-results.json']:
 d=json.loads((S/n).read_text());print(n,json.dumps({k:v for k,v in (d if isinstance(d,dict) else {'list':d}).items() if k not in ['records','rows','results','budget','events','query_result','captured_user_statements']},ensure_ascii=False)[:600])
for p in (S/'manager-api/target/surefire-reports').glob('TEST-*.xml'):
 d=ET.parse(p).getroot().attrib;print(p.name,{k:d.get(k) for k in ['tests','failures','errors','skipped']})

