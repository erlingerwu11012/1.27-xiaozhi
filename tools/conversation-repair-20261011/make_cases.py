import json,hashlib
from pathlib import Path
S=Path(__file__).parent
def t(q,tool=None,**kw):return {'query':q,'tool':tool,**kw}
def segment(kind,n,holdout=False):
 label=f'测试{n}';content=f'吃饭{n}'
 templates=[
  [t('不用了，你给我设个公共提醒吧，提醒我'+content,clarify=True),t('两分钟后','add_reminder',recipient='all'),t('刚才是提醒谁的？',required=['所有人|大家|公共']),t('你查一下还有哪些提醒','reminder_list_pending'),t('好，没事了，别再给我新建了')],
  [t('记一下，我最爱喝美式咖啡啊','memory_add'),t('我爱喝啥？','memory_search',required=['美式']),t('不是啊，现在不喝咖啡了，你改一下','memory_correct',required=['不喝']),t('再查查我现在喝不喝咖啡','memory_search',required=['不喝']),t('我就问问，你不要又改记忆了')],
  [t('你记一下，我的台灯叫'+label+'灯','memory_add'),t('我的台灯叫什么','memory_search',required=[label]),t('把台灯名字那条记忆忘掉吧','memory_forget'),t('刚才那个台灯名字还在记忆里吗','memory_search',forbidden=[label]),t('不是叫你再编一个名字出来啊，直接说有没有')],
  [t('声音给我往上加一点','self_audio_speaker_set_volume',volume=60),t('现在声音多大了','self_get_device_status',required=['60|六十']),t('我就是问一下，别调它'),t('那现在压到最低吧','self_audio_speaker_set_volume',volume=0),t('这次没让你再动，刚才最低是多少',required=['0|零|最低'])],
  [t('亮度弄到百分之九十','self_screen_set_brightness',level=4),t('这是最高档了吗','self_get_device_status',required=['4|四','5|五|不是']),t('我只是问，没让你调'),t('那给我再亮一档','self_screen_set_brightness',level=5),t('现在还有更亮的档吗','self_get_device_status',required=['最高|5|五'])],
  [t('给我弄个闹钟吧，晚上十点','alarm_set',alarms=1),t('查一下我有哪些闹钟','alarm_list',required=['22|十点']),t('不是问你响没响，我问设了啥','alarm_list'),t('把第一个闹钟删掉吧','alarm_delete',alarms=0),t('再看一下还剩几个','alarm_list',required=['没有|空|零|0'])],
  [t('帮我每天六点提醒喝水',clarify=True),t('晚上六点','habit_learn',hour=18),t('你给我看看现在的习惯','habit_list',required=['18|晚上|六点']),t('我就问问时间，不用再给我加了'),t('把第一个喝水习惯删了吧','habit_delete',habits=0)],
  [t('帮我记个不定时便签，买'+label+'牛奶','note_add',notes=1),t('还有啥便签来着','note_list',required=[label]),t('不是要当前卡片，查全部便签','note_list'),t('把第一条便签删了','note_delete',notes=0),t('还有没有便签了','note_list',required=['没有|空|暂无|0|零'])],
  [t('现在屏幕上提醒的是啥','reminder_get_current',card=True),t('这个卡片给我关了吧','reminder_close_current',card=False),t('现在那个卡片还显示吗','reminder_get_current',card=False),t('我只是关卡片，没让你新建东西'),t('好，直接说，不要又逗我')],
  [t('再过十分钟提醒我当前这件事','reminder_action',card_action='secondary'),t('刚才这件事是啥内容','reminder_get_current'),t('这次先跳过，之后的别动','reminder_action',card_action='tertiary'),t('屏幕上现在还有这个卡片吗','reminder_get_current',card=False),t('没叫你删掉以后每天的规则啊')],
  [t('随便聊聊，最近刚买了个书架，还没发货，别替我安排'),t('现在家里还没有新书架，我只是期待把旧书摆出来'),t('不要每句都问我，说说你的看法'),t('店家刚通知发货了，不过我还没收到'),t('我这个书架现在什么状态',required=['发货','没.*收|未.*收'],forbidden=['没发货|未发货'])],
  [t('报告上周已经写好一半，昨天只改了标题，正文昨天没进展'),t('我只是说说工作，不用给我建议'),t('今天先别逗我，也别反问'),t('昨天没写正文，能说整份正文从来没写过吗',required=['不能|不是|不对']),t('那报告到目前为止完成多少',required=['一半|50'])],
  [t('记一下，我的宠物叫'+label+'豆','memory_add'),t('你还记得我宠物叫啥吗','memory_search',identity='unknown',identity_block=True),t('刚才没听出来就直说，别说设备坏了'),t('现在再查查我宠物叫啥','memory_search',identity='restore',required=[label]),t('这条宠物名字记录不要了，忘掉吧','memory_forget')],
  [t('给我设个公共提醒，内容是吃饭',clarify=True),t('这天气怎么突然凉了'),t('刚才那个，就三分钟后','add_reminder',recipient='all'),t('是不是公共的，别给我弄成个人的',required=['公共|所有人|大家']),t('不用再创建，查一下提醒列表','reminder_list_pending')],
  [t('设个公共提醒，提醒我取快递',clarify=True),t('算了，取消这个，先不用'),t('两分钟后'),t('刚才我取消了，你没建吧',no_writes=True),t('现在重新来，两分钟后公共提醒我取快递','add_reminder',recipient='all')],
  [t('把音量设到三十，再把屏幕调到九十','self_audio_speaker_set_volume',also=['self_screen_set_brightness'],volume=30,level=4),t('声音再大一点，屏幕再暗一档','self_audio_speaker_set_volume',also=['self_screen_set_brightness'],volume=40,level=3),t('查查现在音量和亮度','self_get_device_status',required=['40|四十','3|三']),t('我问问最大多少，别帮我调上去','self_get_device_status'),t('不用设置，保持现在就行')],
  [t('我先问问，怎么设置闹钟，不要真设'),t('不是要你现在做，刚才只是举例'),t('现在真的帮我设一个晚上九点的闹钟','alarm_set',alarms=1),t('先不用再操作，告诉我刚才设到几点',required=['21|九点']),t('给我查查闹钟列表','alarm_list')],
  [t('帮我拍一张看看桌上是什么','self_camera_take_photo',required=['杯']),t('再拍一次吧','self_camera_take_photo',required=['杯']),t('这次没拍好就直说，别逗了'),t('你能听出来我是谁吗',required=['测试用户|默认用户|没听出']),t('我没让你看脸，不用拍照')],
  [t('记一下，我出门总带一把蓝色的伞','memory_add'),t('我出门带什么来着','memory_search',required=['伞']),t('你别改记忆，我只是查询啊'),t('伞颜色说错了，是绿色的，你改一下','memory_correct'),t('再查下我带的伞是什么颜色','memory_search',required=['绿'],forbidden=['蓝色'])],
  [t('屏幕给我提亮一点','self_screen_set_brightness',level=4,noise=True),t('我刚才说的，你听到了吧'),t('把声音降到二十','self_audio_speaker_set_volume',volume=20,noise=True),t('查一下现在声音和亮度','self_get_device_status',required=['20|二十','4|四']),t('好，别再重复说一遍了')],
 ]
 rows=templates[kind]
 if holdout:
  substitutions={'你给我':'麻烦帮我','记一下':'帮我记住这个事实：','查一下':'查查','再查查':'再确认下','别逗了':'先别开玩笑，直接回答','两分钟后':'过两分钟','晚上十点':'今晚22点','晚上六点':'下午18点','第一个':'第一项','这个卡片给我关了吧':'把眼前这张卡片收起来','现在家里':'我家现在','声音降到二十':'音量弄成20','百分之九十':'百分之90'}
  for row in rows:
   for a,b in substitutions.items():row['query']=row['query'].replace(a,b)
 return {'id':f'combo-{n:02d}','kind':kind,'holdout':holdout,'turns':rows,'card':kind in {8,9},'seed_memory':False}
groups=[segment(k,k+20*v,v==2) for v in range(3) for k in range(20)]
singles=[]
for i in range(60):
 kind=i%12
 row=[t('先别开玩笑，今天就普通聊两句'),t('你给我把声音改成四十','self_audio_speaker_set_volume',volume=40),t('屏幕调整到百分之九十吧','self_screen_set_brightness',level=4),t('把声音开到最大','self_audio_speaker_set_volume',volume=100),t('我只是说声音有点小，先不用调整'),t('给我查一下音量现在是多少','self_get_device_status',required=['50|五十']),t('帮我定一个今晚十点半的闹钟','alarm_set',alarms=1),t('给我保存一条便签，买牛奶，不定时','note_add',notes=1),t('别调了，我只是问问'),t('你能听出我是谁吗',required=['测试用户|默认用户|没听出']),t('今天的事情真多，我只是吐槽，别给方案'),t('你记一下，我的钥匙放在绿色盒子里','memory_add')][kind]
 if i>=12:row['query']=row['query'].replace('给我','帮我').replace('吧','').replace('先别','暂时别')
 singles.append({'id':f'single-{i:02d}','kind':kind,'holdout':i>=40,'turns':[row],'card':False})
pack={'groups':groups,'singles':singles,'counts':{'segments':60,'combo_turns':300,'standalone':60,'holdout_segments':20}}
p=S/'cases.json';assert not p.exists(),'do not replace a frozen corpus';p.write_text(json.dumps(pack,ensure_ascii=False,indent=2),encoding='utf-8')
(S/'cases.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
print(pack['counts'])
