import json,tarfile
from pathlib import Path
stage=Path(__file__).resolve().parent
names=['core/api/vision_handler.py','core/utils/device_reminder.py','core/websocket_server.py','core/providers/memory/bailian/bailian.py','core/handle/helloHandle.py','core/utils/vision_capability.py','core/providers/tools/device_mcp/mcp_executor.py','core/connection.py','core/handle/abortHandle.py','core/handle/receiveAudioHandle.py','core/utils/tool_harness/models.py','core/utils/tool_harness/runtime.py','core/utils/tool_harness/contracts.py','core/utils/tool_harness/presentation.py','core/utils/tool_harness/domains.py','core/utils/tool_result.py','core/utils/recent_memory.py','core/utils/unified_recipient_resolver.py']
with tarfile.open(stage/'candidate-changes.tgz','w:gz') as archive:
    for name in names:archive.add(stage/'candidate'/name,arcname=name)
(stage/'changed-files.json').write_text(json.dumps(names,indent=2))
