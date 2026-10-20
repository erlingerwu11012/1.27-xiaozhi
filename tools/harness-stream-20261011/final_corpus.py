"""Keep the prior corpus intact; replace its previously exposed holdout separately."""
import json,hashlib,copy
from pathlib import Path
s=Path(__file__).parent
old=json.loads((s/'cases.json').read_text(encoding='utf-8'));new=copy.deepcopy(old)
def t(q,tool=None,**kwargs):return dict(query=q,tool=tool,**kwargs)
def heldout(n):
 label=f'验收{n}';kind=n%5
 rows=[
  [t(f'先帮大家记一个定时事项，内容是取{label}包裹',clarify=True),t('我顺便说一句，今天路上挺安静'),t('接着刚才的事项，五分钟以后','add_reminder',recipient='all'),t('读取一下全部待办事项','reminder_list_pending'),t('这条刚才安排给哪些人，直接说',required=['所有人|公共|大家'])],
  [t(f'请记住这个事实：我最常用的杯子是{label}白杯','memory_add'),t('检索一下我最常用哪个杯子','memory_search',required=[label]),t(f'那条杯子资料改一下，最常用的是{label}黑杯','memory_correct'),t('重新检索最常用的杯子','memory_search',required=['黑杯']),t('把刚才杯子那条资料删除，不要删其他的','memory_forget')],
  [t('音量改到25，屏幕亮度设为二档','self_audio_speaker_set_volume',also=['self_screen_set_brightness'],volume=25,level=2),t('刚才那个屏幕再提亮一档，声音先保持','self_screen_set_brightness',level=3,volume=25),t('查询一下目前两个设置','self_get_device_status',required=['25|二十五','3|三']),t('只是确认一下，不是让你再设置'),t('音量往下减五个点，屏幕别动','self_audio_speaker_set_volume',volume=20,level=3)],
  [t(f'存一张无时间要求的便签：买{label}纸巾','note_add',notes=1),t('读取全部便签给我看看','note_list',required=['纸巾']),t('今天天色不错，我只是随口说说'),t('删除列表里的第一张便签','note_delete',notes=0),t('读一次便签列表，确认没有了','note_list',required=['没有|空|暂无|0|零|没了'])],
  [t('明天就不加了，现在先设每天晚上九点半的闹钟','alarm_set',alarms=1),t('只读取闹钟列表，不修改','alarm_list',required=['21|九点']),t('你说的设置成功，可不表示已经响过',forbidden=['已经响过|早就响了']),t('刚列出来的第一个闹钟帮我删除','alarm_delete',alarms=0),t('请再次读取闹钟列表确认','alarm_list',required=['没有|空|零|0|没了'])]
 ][kind]
 return {'id':f'combo-{n:02d}','kind':100+kind,'holdout':True,'turns':rows,'card':False,'provenance':'new_unrun_holdout_this_plan'}
for g in new['groups'][:40]:g['holdout']=False;g['provenance']='legacy_regression'
new['groups']=new['groups'][:40]+[heldout(n) for n in range(40,60)]
new['legacy_corpus_sha256']=hashlib.sha256((s/'cases.json').read_bytes()).hexdigest()
path=s/'cases-v2.json';assert not path.exists();path.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
(s/'cases-v2.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
print(new['counts'])
