import json,hashlib
from pathlib import Path
S=Path(__file__).parent;pack=json.loads((S.parent/'harness-20261007/pack.json').read_text(encoding='utf-8'));cases=[]
def add(q,tool=None,args=None,group='tool',**kw):cases.append(dict(id=len(cases)+1,query=q,tool=tool,arguments=args or {},group=group,**kw))
for n,f in pack['fixtures'].items():
 for prefix in ['我这边想请你帮个忙，','麻烦处理一下这件事：']:
  add(prefix+f['query'],n,f['arguments'],setup=n)
common={
 'self_audio_speaker_set_volume': [('我听着有点费劲，你把声音弄到六十吧',{'volume':60}),('声音直接开到最大吧',{'volume':100}),('声音压到最低吧',{'volume':0}),('现在把声音提一小格，就十个点',{'relative':10}),('声音比现在低十个点就行',{'relative':-10}),('我想用四成音量，帮我改一下',{'volume':40}),('声音改成九成半吧',{'volume':95}),('把声音开到二十五就好',{'volume':25}),('请将音量调整为百分之八十',{'volume':80}),('我希望这会儿音量是七十，设置一下',{'volume':70}),('能不能帮我把声音设为三十五',{'volume':35}),('帮我把音量往上加十个点',{'relative':10})],
 'self_screen_set_brightness':[('屏幕太刺眼，帮我往下调一档',{'relative':-1}),('屏幕再亮一档吧',{'relative':1}),('我想用最亮的屏幕，给我设置好',{'brightness':5}),('亮度弄到百分之九十',{'brightness':90}),('把屏幕亮度改成九成半',{'brightness':95}),('我想把亮度设成第四档',{'brightness':4}),('屏幕请调到第二档',{'brightness':2}),('帮我把亮度换成百分之七十',{'brightness':70}),('亮度设在百分之六十就行',{'brightness':60}),('屏幕亮度用第三档吧',{'brightness':3}),('能不能把屏幕调到最暗那档',{'brightness':1}),('这会儿请把屏幕弄成百分之八十',{'brightness':80})],
 'alarm_set':[(q,{'hour':h,'minute':m,'repeat_days':r}) for q,h,m,r in [('今晚十点钟叫醒我，给我定个闹钟',22,0,0),('闹钟帮我定在晚上九点半，就这一次',21,30,0),('每天早上七点用闹钟叫我',7,0,127),('工作日七点半设一个闹钟',7,30,62),('每个周末上午八点，帮我定闹钟',8,0,65),('我需要一个今晚十一点的闹钟',23,0,0),('给我加个早上六点四十五的闹钟',6,45,0),('麻烦设置晚上八点十五的闹钟，只响一次',20,15,0),('早上九点定个闹钟，不重复',9,0,0),('晚上十点半帮我安排闹钟',22,30,0),('闹钟定到下午三点，仅一次',15,0,0),('每天晚上八点半设闹钟',20,30,127)]],
 'note_add':[(q,{'text':t,'remind_at':0}) for q,t in [('便签里记一下买面包，不用提醒','买面包'),('帮我存条便签：周末整理书架','周末整理书架'),('记个备忘录，带雨伞，不用定时','带雨伞'),('便签帮我写上记得带钥匙，不设时间','记得带钥匙'),('新建便签，退还图书','退还图书'),('帮我记下便签内容：联系物业','联系物业'),('存个便签，整理旧照片','整理旧照片'),('写条便签，买牛奶，别设置提醒','买牛奶'),('帮我加一条没有提醒时间的便签：清洗水杯','清洗水杯'),('保存便签：检查快递柜','检查快递柜'),('便签写成换灯泡，不定时','换灯泡'),('替我记条便签：明天带书','明天带书')]],
 'add_reminder':[(f'{p}{m}分钟后提醒我{t}',{'content':t,'delay':m}) for p,m,t in [('麻烦你，',10,'喝水'),('帮个忙，',5,'拿快递'),('我需要你',15,'关窗'),('请帮我，',20,'取衣服'),('记得',8,'热牛奶'),('给我设置一下，',12,'带钥匙'),('能不能',6,'看烤箱'),('我想让你',25,'浇花'),('安排一下，',30,'站起来'),('请设置一个提醒，',18,'休息'),('帮我设定，',9,'开会'),('请记一下，',7,'还书')]],
 'reminder_action':[(q,{'action':a}) for q,a in [('好，我已经拿完了','primary'),('快递取到了','primary'),('这件事办完了，卡片可以收了','primary'),('已经取完快递，帮我确认一下','primary'),('这个提醒过五分钟再来','secondary'),('先别响，事项先留着','silence'),('现在这条不用提醒了，明天的别动','tertiary'),('帮我完成当前提醒','primary'),('快递我拿好了，结束这次提醒','primary'),('这次跳过，别删除以后提醒','tertiary'),('卡片先静音，但不要标完成','silence'),('再过十分钟提醒我当前这件事','secondary')]]}
for n,rows in common.items():
 for i,(q,a) in enumerate(rows):add(q,n,a,'common',setup=n,holdout=i>=6)
chats=[
 [('刚买了个书架，还没发货。我就是随便聊聊，别替我安排。',[]),('现在家里还没有这个新书架，我期待把以前的书重新摆出来。',[]),('别每句话都反问我，你直接说说看法。',[]),('店家说已经发货，但我还没有收到。',[]),('只根据我说过的内容，书架现在是什么状态？',['发货','没有|没|未'])],
 [('报告上周写好一半，昨天只改了标题。',[]),('昨天剩下的正文没动。',[]),('不能说整份正文从来没写过吧？',['不能|不对|不是']),('我今天也没继续写。',[]),('整份报告目前完成了多少？',['一半|50'])],
 [('今天有点累，我就是随便说说，别安排任务。',[]),('先别开玩笑，认真听我说。',[]),('也别每一句都问我。',[]),('我把窗帘拉开了，心情好了一点。',[]),('不用安慰我，也别教育我。',[])],
 [('外卖还没到，我还没吃晚饭。',[]),('别说你帮我准备好了什么。',[]),('刚收到通知，外卖已经到楼下了，我还没拿。',[]),('先不用你提醒我，我知道了。',[]),('我现在吃上了吗？',['还没|没有|未'])],
 [('不要调整亮度，我只是问九十是什么意思。',[]),('如果我说把音量调大，你会怎么做？先不要执行。',[]),('“闹钟设好啦”这句话只是举例。',[]),('我不是让你拍照，先解释一下拍照失败可能是什么情况。',[]),('好，就聊到这件事，别结束会话。',[])],
 [('我昨天喝了咖啡，今天没喝。',[]),('明天喝不喝还没决定。',[]),('别替我记录习惯。',[]),('今天没喝不代表我一直不喝，对吧？',['不代表|对|是']),('只根据这段聊天，昨天和今天喝了吗？',['昨天','今天'])],
 [('我想买个台灯，但还没下单。',[]),('刚才下单了，店家还没发货。',[]),('别反问，也不用推荐商品。',[]),('现在店家发货了，但我没收到。',[]),('现在家里已经有这个台灯了吗？',['没有|还没|未'])],
 [('钥匙在包里，门卡在桌上。',[]),('我刚把钥匙放到了抽屉，门卡没动。',[]),('现在不用提醒我拿东西。',[]),('不要开玩笑，我确认一下位置。',[]),('钥匙和门卡分别在哪里？',['抽屉','桌'])]]
for ci,rows in enumerate(chats):
 for i,(q,required) in enumerate(rows):add(q,None,{},'chat',session='chat'+str(ci),required=required,holdout=ci>=4)
for ci in range(6):
 rows=[('查一下我以前说过喜欢什么饮料','memory_search',{'query':'饮料'}),('我之前说错了，把我喜欢咖啡改成我现在不喝咖啡了','memory_correct',{}),('那现在我喝咖啡吗，查一下记忆','memory_search',{})] if ci<3 else [('查一下我之前说过台灯叫什么','memory_search',{}),('忘掉那条台灯叫银杏灯的记忆','memory_forget',{}),('再查查我的台灯叫什么','memory_search',{})]
 for i,(q,n,a) in enumerate(rows):add(q,n,a,'memory',session='mem'+str(ci),setup='memory',memory_step=i,memory_kind='correct' if ci<3 else 'forget')
multis=[
 [('帮我设个今晚十点的闹钟','alarm_set'),('看看我设了什么闹钟','alarm_list'),('把第一个闹钟删掉吧','alarm_delete'),('再查一下还有没有闹钟','alarm_list')],
 [('帮我写条便签：买牛奶，不定时','note_add'),('便签里都记了些什么','note_list'),('第一条便签推迟十分钟再提醒','note_snooze'),('再给我看一下便签','note_list')],
 [('查一下当前声音多大','self_get_device_status'),('声音加十个点吧','self_audio_speaker_set_volume'),('声音弄到九成半','self_audio_speaker_set_volume'),('再看看音量是多少','self_get_device_status')],
 [('这张卡片提醒我什么','reminder_get_current'),('先别响，但还没办完','reminder_action'),('好，快递已经取好了','reminder_action'),('现在还显示什么提醒','reminder_get_current')],
 [('拍一下看看桌上有什么','self_camera_take_photo'),('再拍一次试试','self_camera_take_photo'),('这次拍到什么了','self_camera_take_photo'),('刚才失败是什么原因，先别拍','chat')],
 [('帮我十分钟后提醒喝水','add_reminder'),('这会儿显示的卡片是什么','reminder_get_current'),('快递我拿完了','reminder_action'),('之前设的喝水提醒还在吧，查一下便签','note_list')]]
for ci,rows in enumerate(multis):
 for i,(q,n) in enumerate(rows):add(q,None if n=='chat' else n,{},'multi',session='multi'+str(ci),setup='photo_retry' if ci==4 else None,multi_step=i,holdout=ci==5)
assert len(cases)==240,len(cases)
assert sum(bool(x.get('holdout')) for x in cases)==60
payload=json.dumps(cases,ensure_ascii=False,indent=2).encode();(S/'final-cases.json').write_bytes(payload);print('240 cases, 60 holdout, SHA256',hashlib.sha256(payload).hexdigest())
