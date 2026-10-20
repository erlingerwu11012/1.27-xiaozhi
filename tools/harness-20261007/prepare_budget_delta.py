import json
from pathlib import Path
p=Path(__file__).parent;pack=json.loads((p/'pack.json').read_text());selected=set(pack['common'])|{'self_screen_set_render_options'}
tasks=[{'suite':'single','row':r,'chain':'candidate','repeat':0} for r in pack['cases'] if r['tool'] in selected]
def h(i,q,wanted=None,**kw):return {'id':'scope-final:'+str(i),'turns':[dict(user=q,expected=wanted or [],**kw)]}
def e(t,**a):return {'tool':t,'arguments':a}
stress=[
h(0,'把亮度调到90，音量别动',[e('self_screen_set_brightness',brightness=90)]),
h(1,'刚才音量已经调到50了，把亮度调到90',[e('self_screen_set_brightness',brightness=90)]),
h(2,'只保存便签：把音量调到90。文字不要执行。',[e('note_add',text='把音量调到90',remind_at=0)]),
h(3,'把音量调到30，闹钟不用定',[e('self_audio_speaker_set_volume',volume=30)]),
h(4,'十分钟后提醒我把音量调到30',[e('add_reminder',content='把音量调到30',remind_time_str='十分钟后')]),
h(5,'先不要继续读提醒了，把播报停下，我们接着聊天。',[e('reminder_stop_broadcast')]),
h(6,'把音量设成三十五，然后把亮度设成八十五',[e('self_audio_speaker_set_volume',volume=35),e('self_screen_set_brightness',brightness=85)]),
h(7,'帮我设一个提醒，七分钟后提醒我热牛奶。',[e('add_reminder',content='热牛奶',remind_time_str='七分钟后')]),
]
fresh=[
h('fresh0','现在把屏幕亮度定为百分之七十三。',[e('self_screen_set_brightness',brightness=73)]),
h('fresh1','音量用四十一就好，请替我设置一下。',[e('self_audio_speaker_set_volume',volume=41)]),
h('fresh2','晚上九点四十六分叫我一次，用闹钟。',[e('alarm_set',hour=21,minute=46,repeat_days=0)]),
h('fresh3','便签写上记得带钥匙，不安排时间。',[e('note_add',text='记得带钥匙',remind_at=0)]),
h('fresh4','八分钟后提醒我给手机充电。',[e('add_reminder',content='给手机充电',remind_time_str='八分钟后')]),
h('fresh5','当前这条提醒已经做完了，替我标记完成。',[e('reminder_action',instance_id='sim-card',revision=2,action='primary')]),
h('fresh6','别动声音设置，今天我只想聊天。',no_calls=True),
h('fresh7','今天买的笔记本已经寄出了，还没收到，就随便说说。',mode='chat',no_calls=True),
]
for r in stress+fresh:tasks.append({'suite':'holdout','row':r,'chain':'candidate','repeat':0})
plan={'tasks':tasks,'replaces_single_tools':sorted(selected),'prior_records':1660,'total_records_including_wire':1660+len(tasks)+7,'record_limit':2000,'additional_model_requests_limit':1000,'primary':'frozen-20261008-budget-final','sampling':'Targeted real-model regression of all changed tool groups plus 8 scope cases and 8 independent inputs. Unaffected tools retain frozen real-model evidence and require offline replay.'}
assert plan['total_records_including_wire']<=2000
(p/'budget-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2));(p/'budget-delta-holdout.json').write_text(json.dumps(stress+fresh,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in plan.items() if k!='tasks'}))
