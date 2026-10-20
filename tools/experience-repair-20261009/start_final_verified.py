from pathlib import Path
import json,time,subprocess
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log','final-summary.json']:
 p=S/n
 if p.exists():
  d=S/('aborted-fifth-'+n);assert not d.exists();p.rename(d)
old=json.loads((S/'final-cases.json').read_text());(S/'prior-final-cases-300.json').write_text(json.dumps(old,ensure_ascii=False,indent=2))
a=old[:240]+[{**x,'independent_holdout':False,'prior_failed_holdout':True} for x in old if x['id'] in [328,331,332]]
def add(q,t=None,args=None,session='',**kw):
 a.append({'id':400+len(a)-243,'query':q,'tool':t,'arguments':args or {},'group':'multi' if t else 'chat','session':session,'holdout':True,'independent_holdout':True,**kw})
scenes=[('护照','抽屉','旅行包'),('眼镜盒','书桌','床头柜'),('充电器','客厅','电脑包'),('发票','口袋','文件夹'),('蓝牙耳机','车里','桌面'),('购物袋','门口','厨房'),('公交卡','鞋柜','钱包'),('钢笔','笔筒','文具盒'),('保温杯','办公室','餐桌'),('雨伞','玄关','阳台'),('药盒','柜子','行李箱'),('数据线','电脑旁','工具盒'),('门钥匙','外套','背包侧袋'),('证件袋','卧室','保险柜'),('手套','车后座','衣柜')]
for i,(item,oldplace,newplace) in enumerate(scenes):
 name='chat-fresh-final-'+str(i)
 add(f'{item}先前在{oldplace}。就是聊两句，别替我安排，也不用反问我。',session=name)
 add(f'更新一下，我把{item}移到了{newplace}，{oldplace}那边已经没有了。',session=name)
 add(f'按我刚刚说的，{item}现在放在哪里？直接回答就好。',session=name,required=[newplace])
for q,t,args in [('声音改到四十六','self_audio_speaker_set_volume',{'volume':46}),('再往上加十个点','self_audio_speaker_set_volume',{'relative':10}),('确认一下，现在音量多少，别再调整','self_get_device_status',{})]:add(q,t,args,session='fresh-final-volume')
for q,t,args in [('亮度帮我改为百分之八十','self_screen_set_brightness',{'brightness':80}),('再往上调一档','self_screen_set_brightness',{'relative':1}),('查下现在亮度，不要修改','self_get_device_status',{})]:add(q,t,args,session='fresh-final-brightness')
for q,t,args in [('保存一条便签：带水杯，不用提醒','note_add',{'text':'带水杯','remind_at':0}),('看看便签里记了什么','note_list',{}),('删除一号便签','note_delete',{'index':1})]:add(q,t,args,session='fresh-final-note')
for q,t,args in [('每天早晨七点二十五的闹钟，帮我设一个','alarm_set',{'hour':7,'minute':25,'repeat_days':127}),('我现在都设置了哪些闹钟','alarm_list',{}),('把一号闹钟删掉','alarm_delete',{'index':1})]:add(q,t,args,session='fresh-final-alarm')
for q,t,args in [('眼前的卡片提醒我干什么','reminder_get_current',{}),('当前这件事延后八分钟再提醒','reminder_action',{'action':'secondary','minutes':8}),('这件事处理好了，帮我把当前提醒标记完成','reminder_action',{'action':'primary'})]:add(q,t,args,session='fresh-final-card')
assert len(a)==303 and sum(bool(x.get('independent_holdout')) for x in a)==60
(S/'final-cases.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
(S/'aborted-fifth-note.json').write_text(json.dumps({'reason':'274 rows,4 failures retained: missing live read evidence and note metadata. All three failed independent rows remain in final corpus; 60 new independent holdout rows added.','time':time.time()}))
(S/'quality-priority-final-authorization.json').write_text(json.dumps({'case_limit':2600,'model_limit':1400,'previous_model_limit':1100,'reason':'Latest user priority: repair bugs and experience first, save expense within that objective. One necessary full final batch after free protocol checks; counters retained.','time':time.time()}))
f=(S/'final-console.log').open('w');p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_final.py')],cwd=S,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'final-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}));print(json.dumps({'pid':p.pid,'cases':303,'fresh_holdout':60}))
