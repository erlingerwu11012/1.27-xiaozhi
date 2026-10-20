from pathlib import Path
import json
import os
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
stage=Path(__file__).parent
evidence=stage/'evidence';evidence.mkdir(exist_ok=True)
env=os.environ.copy()
env['PATH']=r'E:\Espressif\tools\ccache\4.12.1\ccache-4.12.1-windows-x86_64'+os.pathsep+env.get('PATH','')
with (evidence/'firmware-build.log').open('w',encoding='utf-8') as log:
    proc=subprocess.Popen([r'E:\Espressif\tools\ninja\1.12.1\ninja.exe','-C','build','-j','4'],cwd=ROOT,env=env,
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
    for line in proc.stdout:
        log.write(line);log.flush()
        if line.startswith('[') or 'error:' in line or 'binary size' in line:print(line,end='',flush=True)
    code=proc.wait()
(evidence/'firmware-build-result.json').write_text(json.dumps({'exit_code':code,'hardware_accepted':False}),encoding='utf-8')
sys.exit(code)
