from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
source=(OUT/'compare_public_prompt_examples.py').read_text()
exec(compile(source.rsplit("for model in ['qwen-plus'",1)[0],str(OUT/'compare_public_prompt_examples.py'),'exec'))
report.update(call_limit=6,calls=0,models=[])
for model in ['qwen3.8-flash','qwen3.8-max']:
 entry={'requested_model':model,'tool_selection_probes':[]};report['models'].append(entry)
 for text,expected in [('声音小一点，调到30吧','self_audio_speaker_set_volume'),('先别调音量，我就问问现在是多少','self_get_device_status'),('打开摄像头让我看实时画面',None)]:
  row={'user':text,'expected_tool':expected,**call(model,[{'role':'system','content':system},user(text)],tools)}
  entry['tool_selection_probes'].append(row)
  print(json.dumps({'model':model,**row},ensure_ascii=False),flush=True)
 (OUT/'qwen-example-tool-probes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'completed':True,'calls':report['calls']}),flush=True)
