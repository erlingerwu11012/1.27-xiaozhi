from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime,timezone
import json
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
STAGE=Path(__file__).parent
CASES={'tts-lifecycle':ROOT/'tools/hardware-followup-20261013/run_tts_host.py',
       'pcm-output':STAGE/'run_audio_output_host.py','spine-pose':STAGE/'run_spine_pose_host.py',
       'server-touch':STAGE/'test_server_touch.py'}
def run(item):
    name,path=item
    result=subprocess.run([sys.executable,str(path)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
    out=STAGE/'evidence';out.mkdir(exist_ok=True)
    (out/(name+'.log')).write_text(result.stdout,encoding='utf-8')
    print(name+': '+('PASS' if result.returncode==0 else 'FAIL'),flush=True)
    if result.returncode:print(result.stdout,flush=True)
    return name,{'exit_code':result.returncode,'log':name+'.log'}
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:results=dict(pool.map(run,CASES.items()))
    report={'at':datetime.now(timezone.utc).isoformat(),'tests':results,
            'passed':all(t['exit_code']==0 for t in results.values()),'hardware_accepted':False}
    (STAGE/'evidence/validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sys.exit(0 if report['passed'] else 1)
