from pathlib import Path
import json,hashlib
s=Path('tools/hardware-followup-20261013')
groups=[]
def r(q,tool=None,**kw):return dict(query=q,**({'tool':tool} if tool else {}),**kw)
def g(name,rows,**kw):groups.append(dict(id=name,turns=rows,**kw))
g('combo-00',[r('那你记一下，我老婆叫秦胜任。','memory_add'),r('存到记忆库里了吗？',required=['存好|保存|记下|核对']),r('不是，是秦蕊，秦朝的秦，花蕊的蕊。帮我更正。','memory_correct'),r('我老婆叫什么？','memory_search',required=['秦蕊'],forbidden=['秦胜任']),r('把刚刚这条配偶姓名记忆忘掉。','memory_forget')])
g('combo-01',[r('记住，我爱喝普洱茶。','memory_add'),r('还记一下，我妻子叫林岚。','memory_add'),r('把爱喝普洱茶改成最爱美式咖啡。','memory_correct'),r('查查我的饮品偏好。','memory_search',required=['美式']),r('把这些记忆全删除了。','memory_forget'),r('我妻子叫什么？','memory_search',required=['林岚'])])
g('combo-02',[r('给我设个公共提醒，吃饭。',clarify=True),r('两分钟后。','add_reminder',recipient='all',notes=1),r('刚才设给谁了？',required=['所有人|公共|大家']),r('查询待提醒的事项。','reminder_list_pending'),r('取消刚才的吃饭提醒。','note_delete',notes=0)])
g('combo-03',[r('你好，今天想跟你随便聊聊。'),r('你把我说的话理解错了，我说的是假设。'),r('我不喜欢你这样调侃，直接回答就行。'),r('如果我说把记忆删掉，这只是举例，不是要你现在做。'),r('我没说要结束对话，继续聊。')])
g('combo-04',[r('帮我查一下音量。','self_get_device_status'),r('把声音调到60。','self_audio_speaker_set_volume',volume=60),r('再大一点。','self_audio_speaker_set_volume'),r('这是最大了吗？',forbidden=['已调|调到100']),r('我只是问，没让你调。')])
g('combo-05',[r('现在这张提醒卡片是什么？','reminder_get_current'),r('提醒你拿快递。'),r('我还没拿到，别把它当完成。'),r('现在我拿到快递了，完成这条提醒。','reminder_action',card_action='primary'),r('刚才那条已经完成了吗？',required=['完成|处理'])],card=True)
g('combo-06',[r('记一下，我喜欢无糖豆浆。','memory_add'),r('顺便聊一句，今天想散散步。'),r('我刚才让你保存什么？',required=['无糖豆浆']),r('给我存进去。',required=['豆浆']),r('查一下我喜欢喝什么。','memory_search',required=['豆浆'])])
g('combo-07',[r('记一下，我妈妈叫张敏。','memory_add'),r('把妈妈姓名改一下。',clarify=True),r('张宁，安宁的宁。','memory_correct'),r('我妈妈叫什么？','memory_search',required=['张宁']),r('删除这条妈妈姓名记忆。','memory_forget')])
# The remaining dialogues exercise distinct wording, relations, feedback and scope.
relations=[('爸爸','陈松','陈林'),('同事','许晴','许青'),('朋友','周然','周燃'),('女儿','小雨','小语'),('儿子','乐乐','悦悦'),('丈夫','沈舟','沈洲'),('配偶','赵悦','赵月'),('母亲','李萍','李平')]
for i,(rel,old,new) in enumerate(relations,8):g(f'combo-{i:02d}',[r(f'帮我存到记忆库，我{rel}叫{old}。','memory_add'),r(f'我{rel}叫什么？','memory_search',required=[old]),r(f'刚才名字说错了，我{rel}叫{new}，把这条改一下。','memory_correct'),r(f'再查查我{rel}的姓名。','memory_search',required=[new],forbidden=[old]),r(f'忘掉刚才这条{rel}姓名记忆。','memory_forget')])
preferences=[('咖啡','拿铁','美式'),('茶','龙井','普洱'),('早餐','豆浆','牛奶'),('水果','苹果','梨'),('运动','慢跑','游泳'),('颜色','蓝色','绿色')]
for i,(topic,old,new) in enumerate(preferences,16):g(f'combo-{i:02d}',[r(f'记住，我喜欢{old}。','memory_add'),r('你先别开玩笑，刚才真的保存了吗？',required=[old+'|保存|记忆']),r(f'我改主意了，改成我喜欢{new}。','memory_correct'),r(f'查一下我的{topic}相关偏好。','memory_search',required=[new]),r('把这次查到的这条偏好删除。','memory_forget')])
g('combo-22',[r('设个提醒。',clarify=True),r('不用了，先聊聊。'),r('我只是问你是不是会设提醒？'),r('现在给我设公共喝水提醒，三分钟后。','add_reminder',recipient='all',notes=1),r('查询我的待提醒事项。','reminder_list_pending')])
g('combo-23',[r('设个早上8点的起床闹钟，只响一次。','alarm_set',alarms=1),r('它响过了吗？',forbidden=['已经响过|刚才响过']),r('查一下所有闹钟。','alarm_list',alarms=1),r('删除刚刚的起床闹钟。','alarm_delete',alarms=0),r('再查查闹钟。','alarm_list',alarms=0)])
for i in range(24,30):
 topic,old,new=preferences[i-24]
 g(f'combo-{i:02d}',[r(f'给我保存这条事实：我更喜欢{old}。','memory_add'),r('现在先别谈记忆，我们随便聊一句。'),r(f'刚才那条改成我更喜欢{new}，其他不用改。','memory_correct'),r(f'我的{topic}偏好是什么？','memory_search',required=[new]),r('只忘掉刚才查出来的这一条。','memory_forget')],holdout=True)
single_queries=[('你好。',None),('我不喜欢你这种说法，请直接一点。',None),('不要把假设当成我真的做过。',None),('存到记忆库了吗？',None),('我没让你停止对话。',None),('你觉得安静的下午适合做什么？',None),('我只是举例说删除记忆，不要执行。',None),('当前音量是多少？','self_get_device_status'),('最高亮度是几档？',None),('帮我把音量设成55。','self_audio_speaker_set_volume'),('屏幕亮度调到4档。','self_screen_set_brightness'),('现在有没有闹钟？','alarm_list'),('帮我设置晚上9点的喝水闹钟，只响一次。','alarm_set'),('当前有没有待提醒事项？','reminder_list_pending'),('请查询我保存的持久事实。','memory_search'),('记一下，我喜欢清淡饮食。','memory_add'),('记住，我的配偶叫顾宁。','memory_add'),('给我存到记忆库里：我家住在测试街道。','memory_add'),('那你记一下，我不喝含糖饮料。','memory_add'),('帮我保存，我的朋友叫江月。','memory_add'),('别逗了，直接说你有没有查询。',None),('刚才我没说心情好，不要替我猜。',None),('如果闹钟响了，我会让你停，这次先不操作。',None),('我问的是是否支持拍照，不是现在拍。',None),('我说的她指我朋友，不是你。',None),('你说得太绕了，用一句话。',None),('今天聊聊咖啡，不用保存。',None),('我只是问如何更正记忆，不要现在修改。',None),('请查一下屏幕和声音的当前状态。','self_get_device_status'),('现在暂时不用设置提醒了。',None)]
singles=[dict(id=f'single-{i:02d}',kind=i%8,turns=[r(q,t)]) for i,(q,t) in enumerate(single_queries)]
pack={'groups':groups,'singles':singles,'requirements':{'dialogues':30,'minimum_turns':5,'singles':30,'holdouts':6}}
blob=json.dumps(pack,ensure_ascii=False,indent=2).encode();(s/'cases-followup.json').write_bytes(blob);(s/'cases-followup.sha256').write_text(hashlib.sha256(blob).hexdigest())
p=s/'run_dialogues.py';t=p.read_text().replace("'/root/prjs/tmp/harness-stream-20261011/baseline-work'","'/root/prjs/tmp/hardware-followup-20261013/baseline-work'").replace('==120 and sum(len(g[\'turns\']) for g in groups)+len(reused)==360','==60 and sum(len(g[\'turns\']) for g in groups)+len(reused)==181');p.write_text(t)
print('dialogues',len(groups),'turns',sum(len(g['turns']) for g in groups)+len(singles))
