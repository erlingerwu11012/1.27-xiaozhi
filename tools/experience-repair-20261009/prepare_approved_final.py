from pathlib import Path
import json,hashlib,time
S=Path(__file__).parent
p=S/'budget.py';s=p.read_text(encoding='utf-8-sig');assert "'model':600" in s;s=s.replace("'model':600","'model':850");p.write_text(s,encoding='utf-8')
p=S/'final-cases.json';old=json.loads(p.read_text(encoding='utf-8'));assert len(old)==280
(S/'prior-final-cases-280.json').write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8');a=old[:240]
def add(q,tool=None,args=None,session='',**kw):
 a.append({'id':281+len(a)-240,'query':q,'tool':tool,'arguments':args or {},'group':'multi' if tool else 'chat','session':session,'holdout':True,'independent_holdout':True,**kw})
scenes=[('移动电源','客厅','背包'),('文件夹','书桌','柜子'),('车钥匙','外套口袋','鞋柜'),('门禁卡','背包','办公桌'),('水杯','厨房','床头'),('耳机','抽屉','电脑旁'),('借来的书','教室','书包'),('体检报告','医院','文件袋'),('雨衣','车后座','储物柜'),('工具箱','阳台','车库'),('运动鞋','玄关','鞋架'),('围巾','衣柜','行李箱'),('票据','钱包','档案盒'),('电脑包','办公室','卧室'),('手表','充电座','手腕上')]
for i,(thing,origin,target) in enumerate(scenes):
 session='chat-independent-'+str(i)
 add(f'{thing}之前在{origin}。我就是聊一下，不用替我安排事情。',session=session)
 add(f'我已经把{thing}放到{target}了，{origin}那里没有了。',session=session)
 add(f'根据我刚刚说的，{thing}现在在哪？直接说位置就好。',session=session,required=[target])
for q,t,args in [('声音请给到四十五就行','self_audio_speaker_set_volume',{'volume':45}),('接着加十个点','self_audio_speaker_set_volume',{'relative':10}),('这次别调，我只是确认目前声音多大','self_get_device_status',{})]:add(q,t,args,session='independent-volume')
for q,t,args in [('屏幕亮度给我放到百分之七十','self_screen_set_brightness',{'brightness':70}),('再亮一格就够了','self_screen_set_brightness',{'relative':1}),('只看现在的亮度，不改设置','self_get_device_status',{})]:add(q,t,args,session='independent-brightness')
for q,t,args in [('存一条便签：带充电线，不要定时','note_add',{'text':'带充电线','remind_at':0}),('翻一下便签，我刚写了什么','note_list',{}),('把编号一的便签删除','note_delete',{'index':1})]:add(q,t,args,session='independent-note')
for q,t,args in [('每天早上六点四十叫我起床，设成闹钟','alarm_set',{'hour':6,'minute':40,'repeat_days':127}),('查查刚才设置的闹钟','alarm_list',{}),('第一号闹钟不用了，删除它','alarm_delete',{'index':1})]:add(q,t,args,session='independent-alarm')
for q,args in [('把眼前这条事延后七分钟提醒',{'action':'secondary','minutes':7}),('先安静，不要算办完',{'action':'silence'}),('这件事已经搞定，帮我完成这次提醒',{'action':'primary'})]:add(q,'reminder_action',args,session='independent-card')
assert len(a)==300 and sum(r.get('independent_holdout',False) for r in a)==60
p.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
(S/'budget-authorization.json').write_text(json.dumps({'model_limit':850,'case_limit':2000,'previous_model_limit':600,'reason':'User authorized continuing with quality first and cost savings second after explicit 850-request proposal','time':time.time(),'prior_core_cases_retained':240,'fresh_independent_holdout':60},indent=2))
print('frozen corpus',len(a),hashlib.sha256(p.read_bytes()).hexdigest())
