from pathlib import Path
import json,time,subprocess
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log','final-summary.json']:
 p=S/n
 if p.exists():
  d=S/('aborted-seventh-'+n);assert not d.exists();p.rename(d)
old=json.loads((S/'final-cases.json').read_text());(S/'prior-final-cases-304.json').write_text(json.dumps(old,ensure_ascii=False,indent=2));bad_sessions={r['case']['session'] for r in map(json.loads,(S/'aborted-seventh-final-results.jsonl').read_text().splitlines()) if r['errors'] and r['case'].get('independent_holdout')}
a=old[:244]+[{**x,'independent_holdout':False,'prior_failed_holdout':True} for x in old if x.get('session') in bad_sessions]
def add(q,t=None,args=None,session='',**kw):
 a.append({'id':600+len(a)-259,'query':q,'tool':t,'arguments':args or {},'group':'multi' if t else 'chat','session':session,'holdout':True,'independent_holdout':True,**kw})
scenes=[('蓝色文件袋','窗台','书柜'),('会议记录本','沙发','公文包'),('备用门卡','桌子','抽屉'),('手表充电座','厨房','卧室'),('订书机','办公室','收纳盒'),('地图册','车里','背包'),('红色围巾','衣架','旅行箱'),('纸质车票','口袋','卡包'),('充电宝','床边','手提包'),('相机镜头盖','茶几','摄影包'),('铅笔盒','课桌','书包'),('泳镜','浴室','运动袋'),('园艺剪刀','花架','工具箱'),('纪念册','床头','柜子'),('收音机','客厅','书房')]
for i,(item,origin,target) in enumerate(scenes):
 name='chat-release-holdout-'+str(i)
 add(f'{item}之前在{origin}。我们就日常聊聊，别老反问，也不用替我安排。',session=name)
 add(f'刚更新了位置，{item}现在放到了{target}，{origin}那边没有了。',session=name)
 add(f'只按我刚才的话，{item}现在在哪里？直接回答位置。',session=name,required=[target])
for q,t,args in [('音量改为四十一','self_audio_speaker_set_volume',{'volume':41}),('再给声音加十个点','self_audio_speaker_set_volume',{'relative':10}),('我只看目前音量是多少','self_get_device_status',{})]:add(q,t,args,session='release-holdout-volume')
for q,t,args in [('请把亮度设成百分之六十','self_screen_set_brightness',{'brightness':60}),('把屏幕再往上调一档','self_screen_set_brightness',{'relative':1}),('确认一下屏幕亮度几档','self_get_device_status',{})]:add(q,t,args,session='release-holdout-brightness')
for q,t,args in [('记一条便签：带雨伞，不要定时','note_add',{'text':'带雨伞','remind_at':0}),('看看现在都有什么便签','note_list',{}),('把编号一的便签删掉吧','note_delete',{'index':1})]:add(q,t,args,session='release-holdout-note')
for q,t,args in [('每天早晨七点十分叫醒我，设闹钟','alarm_set',{'hour':7,'minute':10,'repeat_days':127}),('闹钟列表给我看看','alarm_list',{}),('把第一个闹钟删除','alarm_delete',{'index':1})]:add(q,t,args,session='release-holdout-alarm')
for q,t,args in [('眼前显示的卡片内容是什么','reminder_get_current',{}),('把当前提醒推迟六分钟','reminder_action',{'action':'secondary','minutes':6}),('这件事做完了，标记当前提醒完成','reminder_action',{'action':'primary'})]:add(q,t,args,session='release-holdout-card')
assert len(a)==319 and sum(bool(x.get('independent_holdout')) for x in a)==60
(S/'final-cases.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
(S/'aborted-seventh-note.json').write_text(json.dumps({'reason':'268 rows stopped on malformed boolean relative argument and optional chat questions. All failed chat sessions retained in full;268 free protocol replays now pass.5 strict typing/feedback checks pass.60 new independent holdout rows.','time':time.time()}))
(S/'quality-priority-final-authorization.json').write_text(json.dumps({'case_limit':4000,'model_limit':2000,'reason':'User explicitly prioritizes fixing all bugs and experience over test budget. Paid run stopped on known issues; full free replay used before one final real-model batch. All cumulative counters and failures retained.','time':time.time()}))
f=(S/'final-console.log').open('w');p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_final.py')],cwd=S,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'final-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}));print(json.dumps({'pid':p.pid,'cases':319,'fresh_holdout':60,'prior_failed_sessions':list(bad_sessions)}))
