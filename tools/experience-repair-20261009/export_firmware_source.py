from pathlib import Path
import difflib,json,hashlib,tarfile
S=Path('tools/experience-repair-20261009'); E=S/'evidence'; paths=['main/vision_credentials.h','main/vision_credentials.cc','main/mcp_tools/mcp_tools_camera.cc','main/reminder_coordinator.cc','tools/test_vision_credentials_host.cpp'];patch=[]
for n in paths:
 old=S/'firmware-baseline'/Path(n).name;new=Path(n)
 patch.extend(difflib.unified_diff(old.read_text(encoding='utf-8-sig').splitlines(True),new.read_text(encoding='utf-8-sig').splitlines(True),fromfile='before/'+n,tofile='after/'+n))
(E/'firmware-changes.patch').write_text(''.join(patch),encoding='utf-8')
with tarfile.open(E/'firmware-source-changes.tgz','w:gz') as t:
 for n in paths+['tools/run_vision_credentials_host_test.py']:t.add(n,arcname=n)
(E/'firmware-source-manifest.json').write_text(json.dumps({n:hashlib.sha256(Path(n).read_bytes()).hexdigest() for n in paths},indent=2),encoding='utf-8')
print('Firmware change evidence prepared; no source edits or device operations.')
