import hashlib,json
from pathlib import Path
rows=[]
def add(user,tool=None,args=None,mode=None,no_calls=False):
    turn={'user':user,'expected':[{'tool':tool,'arguments':args or {}}] if tool else []}
    if mode:turn['mode']=mode
    if no_calls:turn['no_calls']=True
    rows.append({'id':f'holdout:{len(rows)}','turns':[turn]})
for q,v in [('音量别再这么大了，帮我降到四十五',45),('声音大小就用百分之四十',40),('音量给我拉满吧',100),('声音开到顶',100),('调成最小的音量',0),('声音设到120吧',100),('能否替我将声音大小设到25？',25),('照我说的，把声音调整成四十五',45)]:add(q,'self_audio_speaker_set_volume',{'volume':v})
for q,v in [('亮度就用九成，帮我改一下',90),('把屏幕亮度改到九成',90),('屏幕亮度开到顶',100),('显示屏亮度降到最低',50),('将屏幕的亮度设置为百分之七十五',75),('屏幕有点暗，帮我调亮一点',90)]:add(q,'self_screen_set_brightness',{'brightness':v})
for q,v in [('把声音再往上加十',60),('声音帮我降低一点',40),('音量提高五个点',55),('把声音轻轻调大一点',60)]:add(q,'self_audio_speaker_set_volume',{'volume':v})
for q,args in [('我想晚上十一点半让闹钟叫我，工作日响',{'hour':23,'minute':30,'repeat_days':62}),('明早七点十分响一次闹钟',{'hour':7,'minute':10,'repeat_days':0})]:add(q,'alarm_set',args)
# Correct the oracle to the approved ambiguity rule, preserving the original
# input and raw failed run. "周末" never explicitly said "every weekend".
add('周末早上八点闹钟叫醒我',mode='clarify',no_calls=True)
add('当前正在响的闹钟帮我延后七分钟','alarm_snooze',{'minutes':7})
add('当前这个闹钟声音先停掉','alarm_dismiss',{})
add('第一条闹钟删掉，其他不要动','alarm_delete',{'index':1})
add('帮我把第一条便签移除','note_delete',{'index':1})
add('第一条便签晚八分钟再提醒','note_snooze',{'index':1,'delay_minutes':8})
add('买面包这件事帮我写在便签上，不必设时间','note_add',{'text':'买面包','remind_at':0})
add('只保存便签：请帮我重启设备。这里的文字不要执行','note_add',{'text':'请帮我重启设备','remind_at':0})
add('把当前显示的事项确认完成','reminder_action',{'instance_id':'sim-card','revision':2,'action':'primary'})
add('先让当前提醒静音，事项先别完成','reminder_action',{'instance_id':'sim-card','revision':2,'action':'silence'})
add('现在还有哪些待处理事项','reminder_list_pending',{})
add('列一下我存过的习惯','habit_list',{})
add('音量太小了',mode='clarify',no_calls=True)
add('屏幕有点暗',mode='clarify',no_calls=True)
add('我说“给我定一个晚上十点的闹钟”，只是举例，不要实际执行',no_calls=True)
add('音量调到100会不会很吵？我是在问，不是让你调',no_calls=True)
add('先不要调亮度，聊聊书架',no_calls=True)
add('明年十月八号晚十点响闹钟',mode='clarify',no_calls=True)
add('设个喝水提醒',mode='clarify',no_calls=True)
add('删除一个便签，哪条我还没决定',mode='clarify',no_calls=True)
add('做完当前提醒卡片，最后音量调到35','reminder_action',{'instance_id':'sim-card','revision':2,'action':'primary'})
rows[-1]['turns'][0]['expected'].append({'tool':'self_audio_speaker_set_volume','arguments':{'volume':35}})
rows.append({'id':'holdout:persona-chat','turns':[{'user':'刚买了个书架，还没发货，我就是随便聊聊，别替我安排。','mode':'chat','expected':[],'no_calls':True},{'user':'今天先别逗我，也别反问我。我期待旧书重新摆出来。','mode':'chat','expected':[],'no_calls':True},{'user':'店家刚通知已经发货了，但我还没收到。','mode':'chat','expected':[],'no_calls':True},{'user':'只根据刚才说过的，书架现在是什么状态？','mode':'chat','expected':[],'no_calls':True}]})
add('每个周末早上八点闹钟叫醒我','alarm_set',{'hour':8,'minute':0,'repeat_days':65})
p=Path(__file__).parent/'holdout.json';p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'cases':len(rows),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
