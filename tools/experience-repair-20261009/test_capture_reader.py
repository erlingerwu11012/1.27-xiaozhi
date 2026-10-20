from pathlib import Path
import importlib.util,tempfile,json,subprocess,sys,base64
p=Path('tools/experience-repair-20261009/capture_device_test.py');spec=importlib.util.spec_from_file_location('capture_test',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
 f=Path(d)/'server.log';f.write_bytes(b'first\n');c={}
 def read():
  request=base64.b64encode(json.dumps(dict(files=[str(f)],cursors=c)).encode()).decode();code="import json,base64;request=json.loads(base64.b64decode('"+request+"'));"+m.READER;r=subprocess.run([sys.executable,'-X','utf8','-c',code],capture_output=True,check=True);return json.loads(r.stdout)['files'][0]
 r=read();assert base64.b64decode(r['data'])==b'first\n';c[str(f)]=dict(identity=r['identity'],offset=r['end'])
 with f.open('ab') as out:out.write(b'next\n')
 r=read();assert base64.b64decode(r['data'])==b'next\n';c[str(f)]=dict(identity=r['identity'],offset=r['end'])
 f.write_bytes(b'x');r=read();assert r['reason']=='truncation_gap_risk' and base64.b64decode(r['data'])==b'x'
 f.rename(Path(d)/'old.log');f.write_bytes(b'rotated');r=read();assert r['reason']=='rotation_gap_risk' and base64.b64decode(r['data'])==b'rotated'
print('PASS: server reader, incremental continuation, truncation and rotation detection. Local temporary files only.')
