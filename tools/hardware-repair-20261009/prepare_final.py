from pathlib import Path
import json
r=Path('tools/hardware-repair-20261009');p=r/'final-cases.json';rows=json.loads(p.read_text(encoding='utf-8'))
queries=['刚忙完，坐下来歇一会儿，随便聊聊，别帮我安排。','今天路上看到一只橘猫，趴在车顶晒太阳。','以前爱听的歌，现在听还是挺好听。','书架刚发货，还没收到，我只是期待。','报告已经写了一半，今天没再写，进度还是一半。','晚饭吃完了，今天就不聊工作了。','别逗我，直接讲讲为什么旧书重看感觉不同。','不用反问我，你说说周末睡懒觉这件事。','我就是抱怨一句，别教育我，也不用安慰。','今天看了场雨，感觉天气一下凉了。','刚换了条桌布，屋里感觉不一样了。','我最近又开始翻以前的相册。','没什么大事，就想聊两句。','以前觉得无聊的电影，最近居然看进去了。','你直接说看法，别每句话都问我。','今天先别开玩笑，我就是有点累。','不是让你提醒我，我只是在说今晚的打算。','说过的就别整段重复了，接着聊别的。','昨天只改了报告标题，不代表正文从来没写过。','东西还在路上呢，别说我收到了。','新杯子还没买，只是在考虑。','我不需要建议，说说你的理解就行。','周末整理书时看到很多以前的批注。','现在不想讨论计划，聊聊阅读吧。','我没说要删除什么，只是说旧东西看着亲切。','先别替我记录，我就讲讲今天碰到的小事。','刚从楼下散步回来，风挺舒服。','今天家里挺安静，我把窗户打开了。','老歌前奏一响，就想到以前坐公交的时候。','今天没什么新鲜事，但也还不错。']
if not any(x['id']=='extra-chat-1' for x in rows):
 for i,q in enumerate(queries):rows.append({'id':f'extra-chat-{i+1}','group':'chat','tool':None,'arguments':{},'query':q,'holdout':True,'independent_holdout':True})
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
# Run only known failing development IDs and their prerequisite session turns.
p=r/'run_model.py';s=p.read_text();s=s.replace("if '--development' in __import__('sys').argv:\n  ids=", "if '--development' in __import__('sys').argv:\n  ids=")
p.write_text(s,encoding='utf-8')
# Safe firmware package without an unearned deployment claim.
s=Path('tools/nvs-habit-renewal-20261007/package_firmware.py').read_text(encoding='utf-8-sig')
s=s.replace("stage=Path(__file__).parent;build=Path('build-nvs64');out=Path('releases/nvs64-habit-renewal-20261007')", "stage=Path('tools/nvs-habit-renewal-20261007');build=Path('build-experience-repair-20261009');out=Path('releases/hardware-repair-20261009')")
s=s.replace('NVS64KB、习惯同步固件','实机问题修复固件（保留64KB NVS布局）').replace('COM9','COM7')
s=s.replace('本包已完整编译、通过主机故障注入和迁移算法测试。','本包已完整编译。实际闹钟调度与持久化源码11项、视觉凭据生命周期源码16项主机测试通过。相机拍摄上传改为有界异步工作任务；卡片关闭不修改业务完成状态。')
s=s.replace("(stage/'firmware-package-result.json')", "(Path('tools/hardware-repair-20261009')/'firmware-package-result.json')")
s="import sys\nsys.path.insert(0,str(__import__('pathlib').Path('tools/nvs-habit-renewal-20261007').resolve()))\n"+s
(r/'package_firmware.py').write_text(s,encoding='utf-8')
