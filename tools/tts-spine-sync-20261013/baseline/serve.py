from pathlib import Path
import os,sys,runpy
ROOT=Path("/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server")
RUNTIME=Path("/root/prjs/releases/harness-followup-20261013/runtime")
candidate=os.environ.get("XIAOZHI_RELEASE_CANDIDATE")=="1"
alternate=candidate or os.environ.get("XIAOZHI_RELEASE_ALTERNATE_PORTS")=="1"
os.chdir(ROOT);sys.path.insert(0,str(RUNTIME));os.environ["FULL_TOOL_HARNESS"]="1"
os.environ["HARNESS_LEDGER_PATH"]=str(Path("/root/prjs/tmp/hardware-followup-20261013/candidate-operations.sqlite3") if candidate else ROOT/"data/harness/operations.sqlite3")
if candidate:os.environ["PERSON_MATERIAL_OUTBOX"]="/root/prjs/tmp/hardware-followup-20261013/candidate-material-outbox.sqlite3"
import config.config_loader as loader
original=loader.get_config_from_api
def configure(c):
 if candidate:
  c=dict(c);c["manager-api"]=dict(c.get("manager-api") or {},url="http://127.0.0.1:18006/xiaozhi",secret=Path("/root/prjs/tmp/hardware-followup-20261013/api-test-secret").read_text(),max_retries=0)
  c["server"]=dict(c.get("server") or {},auth_key=c["manager-api"]["secret"],auth={"enabled":True,"allowed_devices":[]})
 r=original(c);r["server"]=dict(r.get("server") or {},ip="127.0.0.1",port=8270,http_port=8273,broadcast_http_port=8276);r["harness"]=dict(r.get("harness") or {},enabled=True);return r
loader.get_config_from_api=configure
import core.utils.prompt_manager as prompt_manager
prompt_manager.V2_PLATFORM_TEMPLATE_PATH=str(RUNTIME/"agent-base-prompt-v2.txt")
runpy.run_path(str(RUNTIME/"app.py"),run_name="__main__")
