from pathlib import Path
import shutil
stage=Path('/root/prjs/tmp/mcp-prune-20261010');root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
for name,dest in [('retired_tools.py','core/providers/tools/retired_tools.py'),('unified_tool_manager.py','core/providers/tools/unified_tool_manager.py'),('mcp_handler.py','core/providers/tools/device_mcp/mcp_handler.py')]:
 shutil.copy2(stage/name,root/dest)
