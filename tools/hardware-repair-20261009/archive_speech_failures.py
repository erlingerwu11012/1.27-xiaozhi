from pathlib import Path
import json,shutil
S=Path(__file__).parent
review={'passed':False,'automatic_pass':268,'additional_failed_ids':['reg-102','reg-164','reg-180'],'reasons':['brightness reply used requested percentage instead of confirmed level','progress reply swapped last-week progress and yesterday title edit','hypothetical answer leaked tool names and was replaced by a failure message'],'queries_removed':0}
(S/'resume-before-speech-review.json').write_text(json.dumps(review,indent=2))
for suffix in ['results.jsonl','freeze.json','summary.json','console.log']:
 p=S/('resume-final-'+suffix);target=S/('resume-before-speech-'+suffix);assert not target.exists();p.rename(target)
shutil.copy2(S/'regression-summary.json',S/'resume-regression-summary.json')
