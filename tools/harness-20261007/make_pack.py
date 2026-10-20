import json,hashlib
from pathlib import Path
stage=Path(__file__).parent
live=json.loads((stage.parent/'control-diagnosis-20261007/device-live-catalog.json').read_text(encoding='utf-8'))['tools']
server=json.loads((stage/'server-catalog.json').read_text(encoding='utf-8'))
inactive={'get_weather','get_news_from_newsnow','play_music'}
tools={t['function']['name']:dict(t,source='device_mcp') for t in live if t['function']['name'] not in inactive}
tools.update({t['function']['name']:t for t in server})
for name in set(t['function']['name'] for t in server):tools[name]['source']=next(t['source'] for t in server if t['function']['name']==name)
cases={
 'get_lunar':('查2026年10月8日的农历和干支',{'date':'2026-10-08','query':'农历和干支'},'2026年10月8日农历八月廿八，干支丙午年'),
 'get_world_time':('查询东京现在的时间',{'timezone':'Asia/Tokyo'},'🌍 Asia/Tokyo 当前时间：\n2026年10月07日 20:30:00 (Wednesday)\n时区：UTC+9'),
 'handle_exit_intent':('结束我们的对话',{'say_goodbye':'再见'},'退出意图已处理'),
 'memory_search':('查一下我之前说过喜欢什么饮料',{'query':'喜欢的饮料'},{'status':'found','text':'用户喜欢绿茶','source':'local'}),
 'memory_correct':('把我喜欢咖啡的记忆改为喜欢绿茶',{'match':'喜欢咖啡','replacement':'喜欢绿茶'},{'status':'accepted','cloud_sync':'pending'}),
 'memory_forget':('忘掉我喜欢咖啡的那条记忆',{'match':'喜欢咖啡'},{'status':'accepted','cloud_sync':'pending'}),
 'random_decision':('帮我掷一个骰子',{'mode':'dice'},'🎲 掷骰子结果：4 点'),
 'self_get_device_status':('查询设备当前音量和亮度',{}, {'audio_speaker':{'output_volume':50},'screen':{'brightness':80}}),
 'self_audio_speaker_set_volume':('把音量调到三十',{'volume':30},{'ok':True,'volume':30}),
 'self_screen_set_brightness':('把亮度调到百分之九十',{'brightness':90},{'ok':True,'brightness':90}),
 'alarm_set':('给我定一个晚上十点的闹钟',{'hour':22,'minute':0,'label':'闹钟','repeat_days':0},'已设置 22:00 闹钟 [仅一次]'),
 'alarm_list':('查看我设置的闹钟',{},'暂无闹钟'),
 'alarm_delete':('删除编号1的闹钟',{'index':1},'已删除'),
 'alarm_dismiss':('停止正在响的闹钟',{},'[ALARM_DISMISSED]'),
 'alarm_snooze':('正在响的闹钟再过五分钟响',{'minutes':5},'[ALARM_SNOOZED] 5'),
 'note_add':('记一条便签买牛奶，不设提醒',{'text':'买牛奶','remind_at':0},'已记录：买牛奶'),
 'note_list':('列出我的便签',{},'暂无备忘录'),
 'note_delete':('删除编号1的便签',{'index':1},'[NOTE_DELETED]'),
 'note_snooze':('编号1的便签推迟十分钟',{'index':1,'delay_minutes':10},'[NOTE_SNOOZED] 10'),
 'reminder_get_current':('查询当前提醒卡片详情',{}, {'active':True,'instance_id':'sim-card','revision':2,'status':'presented','primary_action':'完成','secondary_action':'稍后提醒','tertiary_action':'跳过'}),
 'reminder_list_pending':('查询我还有哪些待处理提醒',{}, {'items':[]}),
 'reminder_begin_broadcast':('我同意，现在开始逐条播报待办',{},'已开始逐项播报待办'),
 'reminder_next':('正在播报待办，跳到下一项',{},'已切换到下一项，当前事项仍会保留'),
 'reminder_stop_broadcast':('停止待办播报，保留未处理待办',{},'已停止播报，未处理待办会保留'),
 'reminder_action':('把当前提醒标记为完成',{'instance_id':'sim-card','revision':2,'action':'primary'},'提醒已完成'),
 'self_camera_take_photo':('拍一张照片，描述桌上的物品',{'question':'描述桌上的物品'},'桌上有一本书和一个杯子。'),
 'self_camera_identify_person':('请用摄像头识别面前是谁',{}, {'status':'unknown','confirmed':False}),
 'self_screen_set_render_mode':('把屏幕渲染测试模式设为spine，不重启',{'mode':'spine'},{'ok':True,'requires_reboot':True,'next_boot_mode':'spine'}),
 'self_screen_set_render_options':('保存渲染配置v1，SPI频率30MHz，关闭像素比较，不重启',{'profile':'v1','spi_mhz':30,'pixel_diff':False},{'ok':True,'requires_reboot':True,'next_boot_profile':'v1','next_boot_spi_mhz':30,'next_boot_pixel_diff':False}),
 'self_screen_get_render_status':('查看屏幕当前渲染配置',{}, {'mode':'spine','profile':'v1'}),
 'self_screen_get_info':('查看屏幕分辨率',{}, {'width':320,'height':240}),
 'self_get_system_info':('查看硬件系统信息',{}, {'chip':'ESP32-S3','flash_size':16777216}),
 'self_reboot':('现在重启设备',{}, True),
 'habit_learn':('把已分析确认的喝水规律保存为每天8点的习惯规则，提前2分钟，来源auto',{'intent':'drink_water','description':'喝水','hour':8,'minute':0,'advance_minutes':2,'source':'auto','repeat_days':127},'已记录习惯：喝水，每天 08:00 前 2 分钟提醒'),
 'habit_list':('查看我的习惯规则',{},'暂无习惯规则'),
 'habit_delete':('删除编号1的习惯规则',{'index':1},'已删除'),
 'habit_confirm':('确认编号1的习惯提醒已完成',{'index':1},'[HABIT_CONFIRMED] 喝水'),
 'habit_reject':('只跳过编号1的习惯今天这一次，保留规则',{'index':1},'[HABIT_SKIPPED_TODAY] 喝水'),
 'behavior_log':('记录行为日志：意图drink_water，原话喝水，结果conversation，不创建提醒',{'intent':'drink_water','raw':'喝水','outcome':'conversation'},{'intent':'drink_water','raw':'喝水','outcome':'conversation'}),
 'camera_face_enroll_start':('开始采集我的人脸，不填写姓名',{},'[FACE_ENROLL_STARTED]'),
 'camera_face_enroll_cancel':('取消正在进行的人脸采集',{},'采集已取消'),
 'camera_face_enroll_status':('查询人脸采集进度',{}, {'state':'capturing','accepted_count':1,'required_frames':3}),
 'add_reminder':('十分钟后提醒我喝水',{'content':'喝水','remind_time_str':'十分钟后'},'提醒已设好。'),
}
rows=[]
templates=['{}','请{}','麻烦你{}','帮我{}','能不能帮我{}？','我想让你{}','现在请{}','{}，谢谢']
for name,(query,args,body) in cases.items():
 if name not in tools:raise RuntimeError('missing tool '+name)
 for i,t in enumerate(templates):rows.append({'id':name+':'+str(i),'tool':name,'user':t.format(query),'arguments':args,'receipt':body,'group':'positive'})
 for i,t in enumerate(['不要{}','如果我说“{}”会怎样？','“{}”这句话是什么意思？','我只是在举例：{}，不要执行。']):rows.append({'id':name+':negative:'+str(i),'tool':name,'user':t.format(query),'group':'negative'})
common={'self_audio_speaker_set_volume','self_screen_set_brightness','alarm_set','add_reminder','note_add','reminder_action'}
expressions={
 'self_audio_speaker_set_volume':['声音设为30','音量换成三十','把声音大小调至30','我想把音量设成百分之三十','音量30就行','将音量设置为三十','请直接把声音改到30','帮我调整音量到30','能不能把声音调成三十？','音量别用50，改为30','现在把音量降低到30','设成三十的音量'],
 'self_screen_set_brightness':['屏幕亮度设为90','亮度换成九十','把屏幕调到90%的亮度','我想把亮度设成百分之九十','亮度90就行','将亮度设置为九十','请直接把屏幕亮度改到90','帮我调整屏幕亮度到90','能不能把屏幕亮度调成九十？','亮度别用80，改为90','现在把亮度提高到90','设成九十的亮度'],
 'alarm_set':['晚上十点叫醒我，设置一个闹钟','今晚22点的闹钟帮我设一个','定个22:00的闹钟，只响一次','晚上十点整，给我设闹钟','帮我新增一个22点的单次闹钟','到晚上10点让闹钟响','能不能替我定一个今晚十点的闹钟？','我要一个22点的闹钟','晚上十点闹钟，设一下','给我加一条22:00闹钟','闹钟设为晚上十点整，不重复','请把22点的单次闹钟安排好'],
 'add_reminder':['过十分钟叫我喝水','请在10分钟后提醒喝水','再过十分钟提醒一下我喝水','帮我设一个喝水提醒，十分钟后','10分钟后叫我喝水，不是闹钟','我需要十分钟后的喝水提醒','提醒我喝水，时间是十分钟后','能不能过十分钟提醒我喝水？','请创建喝水待办，10分钟后提醒','十分钟后说一声该喝水了','喝水提醒定在十分钟后','到10分钟以后提醒我喝水'],
 'note_add':['把买牛奶记进便签，别定时间','便签记上买牛奶，不要提醒','记录买牛奶这件事，只记下来','帮我新增一条买牛奶便签，无提醒','便签内容是买牛奶，保存一下','记下买牛奶，不需要定时','能不能记个买牛奶便签？不设置提醒','我要一条写着买牛奶的便签','买牛奶写进备忘录，保持无提醒','保存便签：买牛奶','请记住便签买牛奶，不是长期记忆','把买牛奶这几个字保存为便签'],
 'reminder_action':['我做完了，把当前提醒标为完成','把正在显示的提醒完成掉','完成现在这张提醒卡片','点当前提醒的完成按钮','这条提醒办好了，标记完成','把眼前的提醒记为已完成','能不能把当前提醒设成完成？','当前事项已办好，确认完成','帮我完成当前提醒，别删除规则','当前提醒的主按钮帮我执行一下','现在这张提醒标成完成状态','当前卡片对应事项我已完成，请确认']}
for name in common:
 query,args,body=cases[name]
 for i,q in enumerate(expressions[name]):rows.append({'id':name+':extra:'+str(i),'tool':name,'user':q,'arguments':args,'receipt':body,'group':'common'})
complex_cases=[]
for i in range(20):
 v=20+i;b=60+i
 complex_cases.append({'id':f'multi:{i}','turns':[{'user':f'把音量调到{v}，然后把亮度设为{b}','expected':[{'tool':'self_audio_speaker_set_volume','arguments':{'volume':v}},{'tool':'self_screen_set_brightness','arguments':{'brightness':b}}]}]})
for i in range(10):
 v=20+i
 complex_cases.append({'id':f'correction:{i}','turns':[{'user':f'把音量调到{v}','expected':[{'tool':'self_audio_speaker_set_volume','arguments':{'volume':v}}]},{'user':f'改成{v+5}','expected':[{'tool':'self_audio_speaker_set_volume','arguments':{'volume':v+5}}]}]})
for i in range(10):
 h=8+i%3
 complex_cases.append({'id':f'clarify:{i}','turns':[{'user':f'给我定个{h}点的闹钟','mode':'clarify','expected':[]},{'user':'晚上，响一次就行','expected':[{'tool':'alarm_set','arguments':{'hour':h+12,'minute':0,'repeat_days':0}}]}]})
for i in range(10):
 complex_cases.append({'id':f'cancel:{i}','turns':[{'user':f'给我定个{1+i}点的闹钟','mode':'clarify','expected':[]},{'user':'算了，别设了','expected':[]},{'user':'我们聊聊书架吧，不需要工具','expected':[]}]})
for i in range(5):
 complex_cases.append({'id':f'relative:{i}','turns':[{'user':'把音量调到50','expected':[{'tool':'self_audio_speaker_set_volume','arguments':{'volume':50}}]},{'user':'再大声点','expected':[{'tool':'self_audio_speaker_set_volume','arguments':{'volume':60}}]},{'user':'屏幕有点暗','mode':'clarify','expected':[]}]})
for i in range(5):
 complex_cases.append({'id':f'cross-topic:{i}','turns':[{'user':'给我定个十点的闹钟','mode':'clarify','expected':[]},{'user':'先不设了，我只是想说今天有点累','expected':[]},{'user':'晚上还要读书，这只是聊天','expected':[]}]})
pack={'tools':list(tools.values()),'cases':rows,'complex':complex_cases,'fixtures':{n:{'query':q,'arguments':a,'receipt':r} for n,(q,a,r) in cases.items()},'common':sorted(common),'unavailable':{'habit_create':'retired_unbound_gateway_entry','habit_list_manual':'retired_cross_account_list'},'clock':'2026-10-07T19:30:00+08:00','repeats':3}
pack['sha256']=hashlib.sha256(json.dumps(pack,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
(stage/'pack.json').write_text(json.dumps(pack,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'tools':len(tools),'covered':len(cases),'cases':len(rows),'sha256':pack['sha256']}))
