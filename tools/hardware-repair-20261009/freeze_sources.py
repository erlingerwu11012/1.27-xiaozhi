from pathlib import Path
import json,hashlib
S=Path('tools/hardware-repair-20261009');p=S/'changed-files.json';a=json.loads(p.read_text());a['core/utils/tool_result.py']='';p.write_text(json.dumps({n:hashlib.sha256((S/'work'/n).read_bytes()).hexdigest() for n in a},indent=2))
