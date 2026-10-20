from pathlib import Path
import json
R=Path('tools/hardware-repair-20261009');p=R/'final-cases.json';old=json.loads(p.read_text());(R/'initial-cases-preserved.json').write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
keep={'new-memory-0','new-card-0','new-settings-0','new-settings-1','new-chat-a','new-photo','new-time','new-voice'}
rows=[dict(x,independent_holdout=False) for x in old if x['id'].startswith('reg-') or x.get('session') in keep]
audit=[]
for x in rows:
 if x['id'] in {'reg-67','reg-68','reg-114'}:
  audit.append({'id':x['id'],'old_expectation':dict(x),'reason':'User did not specify morning/afternoon; clarification is required, not an inferred morning write.'})
  x.update(tool=None,arguments={},expected_clarify=True,forbidden_tools=['habit_learn','alarm_set'],required=['早上|上午|下午|晚上'])
new=[]
def add(q,t=None,a=None,**kw):
 new.append({'id':f'holdout-{len(new)+1}','query':q,'tool':t,'arguments':a or {},'group':'fresh','holdout':True,'independent_holdout':True,**kw})
queries=[('查查我之前喜欢什么饮料','我现在改喝绿茶了，把喜欢咖啡那条记忆更新一下','刚才我只是问爱喝什么，别给我乱改记忆','之前台灯叫什么那条记忆帮我忘了'),('你记着我喝哪种饮料了吗，查一下','帮我纠正饮料偏好，我现在不喝咖啡，喝绿茶','我想查现在喝什么，并没有要求你更正','把台灯叫银杏灯这件事从记忆里忘掉'),('以前聊过的饮料喜好你查一下','咖啡那条记忆说错了，改成我现在喝绿茶','问你现在喜欢喝啥，就是查询，别修改','帮我忘记台灯的名字那条记忆'),('记忆里说我喝什么来着，帮我找找','我现在喝绿茶，不喝咖啡了，修改一下那条记忆','查一下最新饮料偏好就行，不要更正','银杏灯那个记忆忘掉吧，不用留了')]
for i,qs in enumerate(queries):
 for j,q in enumerate(qs):
  t=['memory_search','memory_correct','memory_search','memory_forget'][j]
  add(q,t,{},session=f'fresh-memory-{i}',setup='memory_search',memory_kind='forget' if j==3 else 'correct',expected_memory='绿茶',expected_absent='银杏灯',required=['咖啡'] if j==0 else ['绿茶'] if j==2 else [])
for i,qs in enumerate([['我眼前这张卡片提醒的是什么呀','把眼前这张提醒卡收起来就行，别修改事项','刚关完，现在还有卡片留在屏幕上吗'],['屏幕正在显示的提醒内容查给我听','当前显示的卡片帮我关闭一下，只关展示','查一下屏幕卡片现在是不是已经关闭了'],['这会儿屏幕上的那条提醒具体是什么','这张提醒卡先给我关掉，不要完成事项','你再查一下现在还有没有提醒卡']]):
 for j,q in enumerate(qs):add(q,'reminder_close_current' if j==1 else 'reminder_get_current',{},session=f'fresh-card-{i}',required=['拿快递'] if j==0 else ['没有|无|不再|已关闭'] if j==2 else [])
for i,seq in enumerate([
 [('把喇叭音量设到二十吧','self_audio_speaker_set_volume',{'volume':20}),('帮我读一下现在音量几成','self_get_device_status',{}),('音量在现在的基础上加十个点','self_audio_speaker_set_volume',{'relative':10})],
 [('给屏幕设个百分之九十的亮度','self_screen_set_brightness',{'brightness':90}),('屏幕现在的亮度是最高档了没有','self_get_device_status',{}),('现在屏幕再往上调一档','self_screen_set_brightness',{'relative':1})],
 [('音量给我设成九十五','self_audio_speaker_set_volume',{'volume':95}),('现在音量往低调十个点','self_audio_speaker_set_volume',{'relative':-10}),('音量数值现在是多少，查一下','self_get_device_status',{})]]):
 for q,t,a in seq:add(q,t,a,session=f'fresh-settings-{i}')
add('帮我重新拍张照片看一眼','self_camera_take_photo',{},session='fresh-photo',setup='photo_retry',multi_step=0)
add('那就再拍一回试试','self_camera_take_photo',{},session='fresh-photo',setup='photo_retry',multi_step=1)
chat=['刚才路边的树叶开始黄了，突然觉得秋天到了。','翻出小时候的照片，有些场景都忘记了。','今天下班早，回家路上绕了条小路。','我就是想聊聊旧书，别给我布置什么任务。','最近又听到一首老歌，想起以前上学的路。','买的花还没开，我挺期待它开花的样子。','新书只是下单，还没送来，你别当成到了。','读同一本书，隔几年看确实会发现不同东西。','不用追问我，你直接讲讲重看旧电影的感觉。','今天不想开玩笑，聊点平常的小事就行。','别安排，也别安慰，我只是说今天过得有点慢。','家里换了个小摆件，感觉整个桌面都不一样。','我没让你提醒我，只是说晚上想看会儿书。','报告昨天已经写完一半，今天没有新进展，别把一半说成零。','不要每次都重复我的原话，你给点自己的看法。','别逗了，认真回答为什么看旧照片会感慨。','昨天没写不代表以前没写，这个意思能理解吧。','我买的椅子还没发货，先在想放哪儿。','今天楼下很安静，连车声都少了。','阳光晒到书桌上，坐着还挺舒服。','偶尔不做计划，也能好好过完一天。','我不需要建议，你听我说说就行。','小时候喜欢的零食，现在吃味道好像不一样。','旧东西留着，有时候只是因为记得当时的事。','不是什么烦恼，就是发现时间过得挺快。','周末想整理书，那只是我的想法，别替我安排。','我没让你记住这些，纯粹随口聊聊。','以前的读书笔记，现在看还挺有趣的。','不用用玩笑岔开，你直接说对这件事的理解。','我只是说今天天气舒服，没有要你执行什么。']
for q in chat:add(q)
assert len(new)==66 and len({x['query'] for x in new})==66
assert not {x['query'] for x in new}&{x['query'] for x in old}
rows+=new
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');(R/'corpus-review.json').write_text(json.dumps({'count':len(rows),'fresh_independent_holdout':len(new),'stronger_time_expectations':audit,'prior_failed_samples_retained':True},ensure_ascii=False,indent=2),encoding='utf-8')
p=R/'run_model.py';s=p.read_text();needle=" matches=[x for x in results if x['tool']==n]";s=s.replace(needle," for pattern in row.get('required',[]):\n  if not re.search(pattern,speech):errors.append('query_fact_missing:'+pattern)\n"+needle);p.write_text(s,encoding='utf-8')
print('final_cases',len(rows),'fresh_holdout',len(new),'tool_coverage',len({x['tool'] for x in rows if x['tool']}))
