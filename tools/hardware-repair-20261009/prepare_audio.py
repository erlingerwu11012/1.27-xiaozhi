from pathlib import Path
import json
R=Path('tools/hardware-repair-20261009')
s=Path('tools/experience-repair-20261009/run_real_audio.py').read_text(encoding='utf-8-sig')
s=s.replace("for text in ['亮度已调到4档。','当前提醒是：拿快递。','本次提醒已确认完成。']:","rows=[json.loads(x) for x in (stage/'final-results.jsonl').read_text().splitlines()]\n texts=[next(x['speech'] for x in rows if x['case']['id']==i and not x['errors']) for i in ['reg-16','reg-45','new-26']]\n for text in texts:")
(R/'run_real_audio.py').write_text(s,encoding='utf-8')
