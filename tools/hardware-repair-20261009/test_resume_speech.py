import bootstrap,json,re
from bootstrap import stage,budget
from core.utils.tool_harness.models import StepResult
from core.utils.tool_harness.reply_composer import unsafe
from core.utils.tool_harness.presentation import safe_speech
r=StepResult(tool='self_screen_set_brightness',state='completed',call_id='test',arguments={'brightness':90},payload={'ok':True,'brightness':4,'brightness_level':4,'duty_percent':95},reply='亮度已调到4档。')
rows=[]
for text,wanted in [('亮度已调到90%。',True),('亮度已经调好了，现在设定在90%。',True),('亮度调到百分之九十了。',True),('亮度设为九成。',True),('亮度已经调好了，现在是4档。',False),('亮度已调到五档。',True),('亮度设为第四档。',False)]:
 budget.reserve('case','speech-facts:'+text);rows.append({'text':text,'passed':unsafe(text,[r])==wanted})
m=StepResult(tool='memory_correct',state='unknown',call_id='unknown',arguments={},payload={'cloud_sync':'disabled','local_applied':True},error='memory_readback_unconfirmed',reply='尚未核对新记忆。')
for text,wanted in [('好的，已记录你现在的偏好是喝绿茶。',True),('因为云端同步未开启，本地无法确认。',True),('更正请求已提交，但尚未查询确认到最新记录。',False),('这次还没有确认记忆修改成功。',False)]:
 budget.reserve('case','memory-unknown-claim:'+text);rows.append({'text':text,'passed':unsafe(text,[m])==wanted})
text=safe_speech('我会先调用 self_get_device_status 查当前状态，再调用 self_audio_speaker_set_volume 设置音量；这次不执行。');budget.reserve('case','speech-hypothetical');rows.append({'text':text,'passed':'self_' not in text and '没有完成' not in text and '查' in text})
pattern=r'上周[^，,。；;]{0,15}(?:停留|主要|只是|只)[^，,。；;]{0,10}标题'
for text,wanted in [('上周的进度主要停留在标题修改上。',True),('上周的进度保持住了，昨天主要是在调整标题。',False)]:budget.reserve('case','progress-scope');rows.append({'text':text,'passed':bool(re.search(pattern,text))==wanted})
summary={'passed':all(x['passed'] for x in rows),'tests':len(rows),'rows':rows};(stage/'resume-speech-regression.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
