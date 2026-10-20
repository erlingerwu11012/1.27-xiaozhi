from pathlib import Path
import json,time,subprocess
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log','final-summary.json']:
 p=S/n
 if p.exists():
  d=S/('aborted-sixth-'+n);assert not d.exists();p.rename(d)
old=json.loads((S/'final-cases.json').read_text());(S/'prior-final-cases-303.json').write_text(json.dumps(old,ensure_ascii=False,indent=2))
a=old[:243]+[{**x,'independent_holdout':False,'prior_failed_holdout':True} for x in old if x['id']==455]
def add(q,t=None,args=None,session='',**kw):
 a.append({'id':500+len(a)-244,'query':q,'tool':t,'arguments':args or {},'group':'multi' if t else 'chat','session':session,'holdout':True,'independent_holdout':True,**kw})
scenes=[('备用眼镜','茶几','收纳箱'),('自行车头盔','车库','储物架'),('收据','手提袋','账本夹'),('手电筒','工具架','床头'),('相机电池','充电器旁','摄影包'),('读书笔记','书房','书包'),('电动车钥匙','桌面','腰包'),('U盘','电脑上','抽屉'),('毛巾','阳台','洗衣篮'),('购物清单','冰箱门','手机壳里'),('领带','衣架','衣柜'),('鼠标','电脑包','办公桌'),('会员卡','卡包','钱包'),('相册','柜子','客厅'),('跳绳','玄关','运动包')]
for i,(item,origin,target) in enumerate(scenes):
 name='chat-last-holdout-'+str(i)
 add(f'{item}原先放在{origin}。随便聊聊，你不用安排什么，也别老反问。',session=name)
 add(f'刚才我把{item}放进了{target}，已经不在{origin}了。',session=name)
 add(f'根据前面这些话，{item}现在在哪里？直接告诉我位置。',session=name,required=[target])
for q,t,args in [('把声音调到四十三','self_audio_speaker_set_volume',{'volume':43}),('再加十个点就行','self_audio_speaker_set_volume',{'relative':10}),('声音现在有多大，查一下就行','self_get_device_status',{})]:add(q,t,args,session='last-holdout-volume')
for q,t,args in [('屏幕亮度弄到百分之七十','self_screen_set_brightness',{'brightness':70}),('再调亮一档吧','self_screen_set_brightness',{'relative':1}),('我只想看现在亮度是多少','self_get_device_status',{})]:add(q,t,args,session='last-holdout-brightness')
for q,t,args in [('存一条备忘录：带钥匙，不设提醒','note_add',{'text':'带钥匙','remind_at':0}),('翻翻我写过的便签','note_list',{}),('一号便签不要了，删掉吧','note_delete',{'index':1})]:add(q,t,args,session='last-holdout-note')
for q,t,args in [('给我设每天早上六点二十分的闹钟','alarm_set',{'hour':6,'minute':20,'repeat_days':127}),('看一下我的闹钟列表','alarm_list',{}),('删掉第一号闹钟','alarm_delete',{'index':1})]:add(q,t,args,session='last-holdout-alarm')
for q,t,args in [('现在卡片上提醒的是什么事情','reminder_get_current',{}),('这条当前提醒往后推迟九分钟','reminder_action',{'action':'secondary','minutes':9}),('当前的这件事办好了，标记完成吧','reminder_action',{'action':'primary'})]:add(q,t,args,session='last-holdout-card')
assert len(a)==304 and sum(bool(x.get('independent_holdout')) for x in a)==60
(S/'final-cases.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
(S/'aborted-sixth-note.json').write_text(json.dumps({'reason':'303 complete,298 passed.5 query failures preserved.303 recorded-decision replays now pass free,49 final regressions and13 read boundary checks pass. All failed rows retained,60 new holdout samples.','time':time.time()}))
(S/'quality-priority-final-authorization.json').write_text(json.dumps({'case_limit':3300,'model_limit':1700,'previous_model_limit':1400,'reason':'User prioritizes repair and experience over budget. Necessary free full replay and one full real-model final revalidation; counters retained, no paid tests in background beyond this batch.','time':time.time()}))
f=(S/'final-console.log').open('w');p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_final.py')],cwd=S,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'final-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}));print(json.dumps({'pid':p.pid,'cases':304,'fresh_holdout':60}))
