import hashlib,json,sys,unittest
from pathlib import Path
root=Path('/root/prjs/tmp/qwen37-official-release-20261007')
prod=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
name='core/utils/hardware_billing.py'
old=(prod/name).read_text();anchor='allowed = {"qwen-plus":'
assert old.count(anchor)==1
target=root/'xiaozhi-server'/name
target.write_text(old.replace(anchor,'allowed = {"qwen3.7-plus": {"llm", "summary", "habit"},\n               "qwen-plus":'))
manifest=json.loads((root/'source-manifest.json').read_text())
manifest['python:'+name]={'before':hashlib.sha256((prod/name).read_bytes()).hexdigest(),'after':hashlib.sha256(target.read_bytes()).hexdigest()}
(root/'source-manifest.json').write_text(json.dumps(manifest,indent=2))
sys.path.insert(0,str(prod))
import core.utils.hardware_billing as hw
exec(compile(target.read_text(),str(target),'exec'),hw.__dict__)
for op in ['llm','summary','habit']:
 assert hw.provider_context({'hardware_billing':True,'hardware_account_id':'1','hardware_operation':op,'model_name':'qwen3.7-plus'})=={'account_id':'1','operation':op}
for op in ['vision','tts']:
 try:hw.provider_context({'hardware_billing':True,'hardware_account_id':'1','hardware_operation':op,'model_name':'qwen3.7-plus'})
 except ValueError:pass
 else:raise AssertionError('unexpected cross-operation permission')
sys.path.insert(0,str(prod/'test'))
result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromName('test_hardware_billing_proof'))
assert result.wasSuccessful()
prepared=json.loads((root/'prepared.json').read_text());prepared['source_files']=manifest;prepared['hardware_python_tests']=result.testsRun
(root/'prepared.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2))
print(json.dumps({'hardware_model_permission_verified':True,'existing_signature_tests':result.testsRun,'passed':True}))
