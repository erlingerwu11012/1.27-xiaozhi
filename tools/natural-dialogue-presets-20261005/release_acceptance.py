"""Final acceptance uses fresh contrasts and records every response, including failures."""
from pathlib import Path
bootstrap=Path(__file__).with_name('live_prompt_acceptance.py').read_text().split('training=')[0]
bootstrap=bootstrap.replace("OUT/'live-prompt-acceptance.json'", "OUT/'release-acceptance.json'")
bootstrap=bootstrap.replace('temperature=0.7','temperature=0.4').replace("'temperature':0.7","'temperature':0.4")
exec(compile(bootstrap, '<candidate-bootstrap>', 'exec'))
report['round']=3
report['temperature']=0.4
report['validation_policy']='Fresh unseen wording; no excluded failures; round one and two preserved.'
cases=[
 ('否定与纠正',['那个台灯下礼拜才发货，我现在先想一下摆哪里。','不是已经收到货，它还没发出呢。']),
 ('完成状态',['这份表格还差好几页没填，我只是打开了文件。','别说我弄完了，现在只有文件打开了。']),
 ('收住人格',['我今天不想听俏皮话，也不要方案。刚才开了好久的会。','只是聊聊，不用帮我设任何提醒。']),
 ('闲聊不派任务',['本来想修一下抽屉，后来一直在看综艺。']),
]
for preset in presets:
 for title,inputs in cases:scene('qwen3.8-flash',preset,title,inputs,'heldout_scenarios')
for preset in (presets[0],presets[4],presets[-1]):
 for title,inputs in cases:scene('qwen3.8-max',preset,title,inputs,'model_comparison')
tools=[{'type':'function','function':{'name':'self_audio_speaker_set_volume','description':'设置设备音量。','parameters':{'type':'object','properties':{'volume':{'type':'integer','minimum':0,'maximum':100}},'required':['volume']}}},
 {'type':'function','function':{'name':'self_get_device_status','description':'查询设备音量和亮度。','parameters':{'type':'object','properties':{}}}},
 {'type':'function','function':{'name':'self_camera_take_photo','description':'拍一张静态照片并识别，不支持实时预览。','parameters':{'type':'object','properties':{'question':{'type':'string'}},'required':['question']}}}]
for preset in (presets[0],presets[4],presets[-1]):
 for text,expected in [('声音有点大，帮我设成25','self_audio_speaker_set_volume'),('现在音量多少？只查，不用调整','self_get_device_status'),('要实时看摄像头画面，不要给我拍照片',None),('解释一下他说的“把声音设置为25”是什么意思',None),('替我拍一张，看看眼前这个杯子','self_camera_take_photo')]:
  row={'preset':preset['id'],'user':text,'expected_tool':expected,**call('qwen3.8-flash',[{'role':'system','content':build(preset['prompt'])},user(text)],tools)}
  row['native_selection_pass']=[t['name'] for t in row.get('tool_calls',[])]==([expected] if expected else [])
  report['tool_probes'].append(row);save()
print(json.dumps({'completed':True,'calls':report['calls'],'native_selection_pass':sum(x['native_selection_pass'] for x in report['tool_probes']),'native_selection_total':len(report['tool_probes'])}))
