from pathlib import Path
import json,time,hashlib
S=Path(__file__).parent
rows=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()]
assert len(rows)==276 and all(not r['errors'] for r in rows)
review={'passed':True,'reviewed_cases':276,'results_sha256':hashlib.sha256((S/'resume-final-results.jsonl').read_bytes()).hexdigest(),'reviewed_at':time.time(),'method':'All final user/assistant speech reviewed alongside automated parameter, receipt, persisted state, readback, TTS and history checks. Prior failed runs preserved.','non_blocking_quality_notes':[{'case':'reg-179','note':'Hypothetical brightness explanation includes an unnecessary speculative maximum-level example. Actual setting tests consistently verify 90 percent maps to level 4; this reply does not assert or perform a device setting. Avoid presenting test pass as perfect natural conversation.'},{'case':'holdout-62','note':'Chat still uses occasional canned phrasing; no unwanted operation or repeated playback.'}],'hardware_evidence':False}
(S/'resume-final-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2))
print(json.dumps({'reviewed_cases':276,'passed':True,'non_blocking_quality_notes':len(review['non_blocking_quality_notes'])}))
