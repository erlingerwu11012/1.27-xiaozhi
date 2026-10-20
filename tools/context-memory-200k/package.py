"""Local: package this increment's sources only, never credentials or data."""
from pathlib import Path
import hashlib,json,tarfile
ROOT=Path(__file__).resolve().parents[2]
SERVER=ROOT/'tmp/bailian-memory-product/server'
OUT=ROOT/'tmp/context-memory-200k'
OUT.mkdir(exist_ok=True)
python_files=['core/utils/context_window.py','core/utils/dialogue.py','core/utils/person_identity.py','core/utils/person_directory_sync.py','core/utils/person_short_memory.py','core/utils/recent_memory.py','core/utils/prompt_manager.py','core/connection.py','core/handle/reportHandle.py','config/manage_api_client.py','core/providers/asr/base.py','core/providers/tts/base.py','core/providers/llm/base.py','core/providers/llm/openai/openai.py','core/providers/tools/server_plugins/plugin_executor.py','core/providers/memory/bailian/bailian.py','plugins_func/functions/person_memory.py','test/test_context_memory_200k.py']
java_files=['agent/dto/AgentChatHistoryReportDTO.java','agent/entity/AgentChatHistoryEntity.java','agent/service/biz/impl/AgentChatHistoryBizServiceImpl.java','agent/controller/AgentController.java','personmemory/RecentArchiveService.java','personmemory/PersonMemoryController.java','personmemory/PersonMemoryService.java','useridentity/service/AccountIdentityStateService.java']
files=['main/xiaozhi-server/'+p for p in python_files]+['main/manager-api/src/main/java/xiaozhi/modules/'+p for p in java_files]
files+=['main/xiaozhi-server/test/test_person_memory_chat_init.py']
files+=['main/xiaozhi-server/test/test_prompt_pipeline_v2.py','main/manager-api/src/main/java/xiaozhi/modules/personmemory/PersonTurnDTO.java']
files+=['main/xiaozhi-server/test/test_identity_snapshot_request.py']
files+=['main/manager-api/src/main/resources/db/changelog/'+p for p in ['db.changelog-master.yaml','202609292100_context_archive.sql']]
files+=['main/manager-api/src/test/java/xiaozhi/modules/personmemory/RecentArchiveServiceTest.java']
files+=['main/manager-api/src/test/java/xiaozhi/modules/personmemory/RecentArchiveDatabaseTest.java']
with tarfile.open(OUT/'overlay.tar.gz','w:gz') as tar:
    for name in files:tar.add(SERVER/name,arcname=name)
manifest={n:hashlib.sha256((SERVER/n).read_bytes()).hexdigest() for n in files}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'files':len(files),'archive_bytes':(OUT/'overlay.tar.gz').stat().st_size}))
