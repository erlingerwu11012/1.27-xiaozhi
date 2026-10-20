from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
gateway=OUT/'gateway-candidate'
p=gateway/'relay/billing/ratio/model.go'
text=p.read_text()
text=text.replace('var ModelRatio = map[string]float64{', 'var ModelRatio = map[string]float64{\n "qwen3.8-flash": 0.8 / 1000 * RMB,\n "qwen3.8-max": 12.0 / 1000 * RMB,',1)
text=text.replace('var CompletionRatio = map[string]float64{','var CompletionRatio = map[string]float64{\n "qwen3.8-flash": 2.7 / 0.8,\n "qwen3.8-max": 36.0 / 12.0,',1)
assert text.count('"qwen3.8-flash":')==2
p.write_text(text)
original=Path('/root/prjs/tmp/natural-dialogue-20261003/run_regression.py').read_text()
original=original.replace("ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')", "ROOT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005/worktree/main/xiaozhi-server')")
original=original.replace('OUT=ROOT.parents[1]', "OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')")
original=original.replace("names=['test_operation_control'", "names=['test_conversation_contract','test_hardware_billing_proof','test_operation_control'")
(OUT/'run_regression.py').write_text(original)
print('candidate pricing defaults and regression runner prepared')
