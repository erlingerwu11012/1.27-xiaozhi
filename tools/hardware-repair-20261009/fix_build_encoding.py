from pathlib import Path
p=Path('main/mcp_tools/mcp_tools_camera.cc');p.write_text(p.read_text(encoding='utf-8-sig'),encoding='utf-8')
p=Path('tools/hardware-repair-20261009/build.ps1');s=p.read_text(encoding='utf-8-sig').replace("$ErrorActionPreference = 'Stop'", "$ErrorActionPreference = 'Stop'\n$env:PYTHONUTF8='1'\n$env:PYTHONIOENCODING='utf-8'");p.write_text(s,encoding='utf-8')
