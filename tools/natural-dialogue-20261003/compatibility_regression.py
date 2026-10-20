"""Run compatibility modules in separate, network-denied interpreters."""
import os, sys, json, subprocess, runpy, socket, unittest
from pathlib import Path
from unittest.mock import MagicMock
ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
if os.environ.get('REGRESSION_BASELINE')=='1':ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
MODULES=['test_qwen3_asr_realtime','test_utterance_state','test_device_reminder','test_camera_mcp_tools',
 'test_account_owner_and_reminder','test_identity_snapshot_request','test_recipient_resolver',
 'test_unified_recipient_outbound','test_person_memory_identity','test_person_memory_tools',
 'test_person_memory_recovery','test_person_memory_chat_init','test_memory_continuity',
 'test_multi_device_isolation','test_reminder_card_converge','test_reminder_control',
 'test_reminder_interaction','test_websocket_session','test_interaction_lifecycle_regression',
 'test_device_send_auth','test_device_send_api','test_card_action']
if '--case' in sys.argv:
    name=sys.argv[-1];assert name in MODULES
    sys.argv=[str(ROOT/'test'/f'{name}.py')]
    os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'test'))
    def denied(*args,**kw):raise AssertionError('network forbidden in offline regression')
    socket.socket.connect=denied;socket.socket.connect_ex=denied;socket.create_connection=denied
    import config.logger
    config.logger.setup_logging=lambda:MagicMock()
    import config.config_loader as loader
    loader.get_config_from_api=lambda config:dict(config,read_config_from_api=False)
    runpy.run_path(str(ROOT/'test'/f'{name}.py'),run_name='__main__')
else:
    if os.environ.get('REGRESSION_BASELINE')=='1':MODULES=['test_device_reminder','test_camera_mcp_tools','test_recipient_resolver']
    rows=[]
    for name in MODULES:
        try:
            result=subprocess.run([sys.executable,__file__,'--case',name],capture_output=True,text=True,timeout=45)
            output=result.stdout+'\n'+result.stderr
            (OUT/f'compat-{"baseline-" if os.environ.get("REGRESSION_BASELINE")=="1" else ""}{name}.log').write_text(output)
            rows.append({'module':name,'exit_code':result.returncode,'success':result.returncode==0 and '[FAIL]' not in output,'failure_lines':[line for line in output.splitlines() if '[FAIL]' in line or line.startswith('FAIL:') or line.startswith('ERROR:')][-20:]})
        except subprocess.TimeoutExpired:rows.append({'module':name,'success':False,'error':'timeout'})
        print(json.dumps(rows[-1]),flush=True)
    (OUT/('compatibility-baseline.json' if os.environ.get('REGRESSION_BASELINE')=='1' else 'compatibility-regression.json')).write_text(json.dumps(rows,indent=2))
