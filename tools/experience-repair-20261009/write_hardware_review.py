from pathlib import Path
import json,datetime
S=Path('tools/experience-repair-20261009');R=Path(json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'))['output']);turns=json.loads((R/'test-transcript.json').read_text(encoding='utf-8'));receipts=json.loads((R/'test-receipts.json').read_text(encoding='utf-8'));status=json.loads((R/'status.json').read_text());manifest=json.loads((R/'manifest.json').read_text());tz=datetime.timezone(datetime.timedelta(hours=8));stamp=lambda ns:datetime.datetime.fromtimestamp(ns/1e9,tz).strftime('%Y-%m-%d %H:%M:%S');user_observations={'alarm_1740':'用户确认：没有响铃，也没有闹钟卡片','reminder_echo':'用户确认：“该提醒内容为：吃饭吧”由设备自己播报'};(R/'user-confirmations.json').write_text(json.dumps(user_observations,ensure_ascii=False,indent=2),encoding='utf-8')
issues=[
('01','最高','闹钟保存成功，但连续聊天中不响','17:36:43设置17:40闹钟成功；17:40无触发记录；用户确认没有铃声和卡片。','固件用 clock_ticks_%60 检查闹钟，但每次 SetDeviceState 都将 clock_ticks_ 清零。此次持续在说话/聆听间切换，无法达到60。','已确认：现场、日志与源码一致。',[(2037,2067)]),
('02','最高','把“到点了”误当成“已完成”，执行了非请求写操作','17:36:16用户仅说“哦，到点吃饭了呀”，模型却执行 reminder_action primary。固件完成卡片并删除 note id=10。','模型规划允许把到点应答当作完成授权；回执保护只证明执行成功，未保护操作是否由用户要求。','已确认实际发生；不是口头虚报。',[(1924,1970)]),
('03','最高','设备播报被自己的麦克风重新识别成用户消息','17:36:12 ASR识别“该提醒内容为：吃饭吧”，声纹0.113未过阈值，随后启动工具查询。用户确认此话由设备自己播报。','提醒播报与交互收音之间存在回声回灌；具体需区分本地提醒音频的AEC参考、收音时序和队列残留。','回灌已确认；具体音频机制待定位。',[(1884,1912)]),
('04','高','音量查询失败两次，设置本身成功','17:34:59、17:35:39询问当前音量，回复“状态未包含所查询的数值”。此前设备确实把音量从100调至90。','真实固件返回 audio_speaker.volume，服务端播报适配只取顶层 volume 或 audio_speaker.output_volume。相对调节路径有另一套取值逻辑，所以设置可成功而查询失败。','源码已定位。',[(1593,1620),(1760,1778)]),
('05','高','两次拍照采集成功，但最终只说未确认','17:39:28和17:43:25调用拍照；固件成功采集640x480图像并上传，第二次明确经过HTTP200路径；服务端均给 unverified_receipt。','视觉HTTP返回 success/action/response JSON封装，固件将整段返回为MCP文本；Harness解包成dict后，拍照契约只接受纯字符串，未适配成功封装。日志未保存原始回包正文，尚不能评审识物文本质量。','源码格式缺口已定位，采集和回执状态有双端证据。',[(2520,2537),(3213,3233)]),
('06','高','查询最高亮度被当成需要写操作的请求','“这是最高档吗”先多余反问；补充“屏幕的亮度是不是最高了已经”后，两次 write_goal_requires_write_steps，最终报操作失败。','查询语义与写目标识别冲突，极值词不能直接等价于设置极值。','错误类别已确认，具体规划与约束来源需进一步跟踪。',[(1670,1737)]),
('07','高','含糊提醒没有先问时间，拒绝原因又丢失','“提醒我待会儿吃饭”被下发 add_reminder；时间解析明确 parse_failed，却回复“尚未确认提醒的完成结果”。','缺少提前澄清；明确的参数解析失败未保留为可理解的澄清结果，被降格为unknown。','日志已定位。',[(1261,1287)]),
('08','高','第一次删除闹钟只查不删，重复才成功','17:42:03要求删除，只调用alarm_list然后失败；17:42:17再说一次，才查询并执行alarm_delete，固件确认删除id=1。','多步目标有时未连续完成。首次原因还需结合规划细节进一步核对，不能仅归咎于声纹。','失败现象已确认，根因未完全定位。',[(2992,3015),(3036,3072)]),
('09','高','信息卡无法语音关闭，删除后还显示旧闹钟列表','17:42:31要求关闭卡片，模型选择reminder_action tertiary；设备返回not_actionable。之后仍显示已经删除的闹钟条目，待机后还播放该信息卡提示音。','信息展示卡没有可用的关闭动作；队列里的旧查询结果未随删除失效。日志出现95条information due，包含多张排队信息卡，不应当作95次用户提醒。','关闭失败与陈旧展示已确认；排队更新机制待进一步定位。',[(3093,3134)]),
('10','高','时间判断和已响事实相互矛盾','17:41说17:40闹钟“还没到”；又说“还没到…早就响过了”；随后改说“没响呢”。用户确认实际未响。','聊天回答未以真实时钟比较和触发证据为依据；查闹钟时只返回数量/屏幕已显示，没有给用户可核对的触发状态。','实际错误原文已确认。',[(2751,2974)]),
('11','中高','问“听出来我是谁”，却调用人脸识别','17:39:15询问声音身份，选择self_camera_identify_person，结果no_face。','工具选择没有区分听声音与看人脸；本轮还有16次声纹低于0.4，其中至少一次是设备自身回声，不能据此计算人的识别准确率或直接决定降低阈值。','选错模态与低分告警已确认。',[(2479,2501)]),
('12','中高','用户抱怨后仍反复挤兑，跨轮重复相同话术','“我要是太聪明，显得你多没面子”多轮重复；用户质疑时还回复“你自己心虚了吧”。','本轮重复主要是模型跨轮重复生成梗，并非已证明TTS包重播。用户人格可以保留，但未及时接住负面反馈、停止重复。','对话原文已确认。',[(2357,2375),(2561,2730)]),
('13','中高','拍照期间音频编码队列积压并丢帧','17:39:33至17:39:34至少20条完整Encode queue full告警，另有交错残行；第二次拍照encode_queue=19。','与拍照上传时间重叠，音频处理存在压力；具体CPU、任务或锁争用尚需定位，不能归因Wi-Fi。','积压和丢帧已确认，根因待查。',[]),
('14','中','触摸屏I2C读取异常、点击未命中','多个时段出现FT5x06 I2C read error；另有点击坐标落在卡片外的touch_ignored。','总线读取异常已确认；不应把所有点击未命中都归因I2C，仍需核对坐标映射与硬件时序。','错误日志已确认，具体硬件/驱动原因待查。',[]),
('15','中','“待机吧”只口头答应，没有立即退出','17:43:42说“行，你待机吧”，未调用handle_exit_intent；仍继续聆听，17:44:19才因30000ms空闲回待机。','退出意图没有被转换为退出操作。最后的WebSocket local_close与正常空闲退出一致，不作为网络断连故障。','双端日志已确认。',[(3267,3278)]),
('16','中高','部分描述性反馈未经澄清直接改变设备状态','“屏幕太亮…怎么办”“说话声音稍微有点小声”触发亮度/音量设置。','与此前约定的独立状态描述先澄清不一致。上下文明确的调节请求应与单纯描述区分。','实际调用已确认。',[(1401,1530)]),
]
lines=['# 本次实机对话测试问题汇总','',f'采集窗口：{stamp(manifest["started_ns"])} 至 {stamp(status["at_ns"])}（北京时间）。COM7/115200；目标设备 ac:a7:04:fd:20:2c。','',f'已停止采集。记录48轮进入LLM的消息，其中一轮经用户确认是设备自身播报回灌。27条Harness回执：23 completed、3 unknown、1 failed。**此比例不是用户目标完成率**：completed包含查询、错误语义下执行成功的操作及最终播报错误。','', '采集器没有记录SSH断线、串口重连或日志轮换缺口。固件原始日志505330字节，包含115个NUL和多处行交错；原始字节保留，但这不证明设备输出端完全无损。服务端采集含开始前回填，分析已按17:32:22切除旧记录。','', '本轮只定位和汇总，没有修改或部署服务端/固件，没有追加付费模型测试。','']
for ident,priority,title,phenomenon,reason,certainty,ranges in issues:
 lines += [f'## {ident}．{title}（优先级：{priority}）','',phenomenon,'','原因与边界：'+reason,'','证据状态：'+certainty,'']
 for lo,hi in ranges:lines.append(f'- [服务端原文，第{lo}行]({(R/"server-0.log").as_posix()}:{lo})')
 if not ranges:lines.append(f'- [按接收时间对齐的固件日志]({(R/"firmware-timed.log").as_posix()})')
 lines.append('')
lines += ['## 之前模拟验收的缺口','','- 模拟器把音量字段写成audio_speaker.output_volume，而真实固件为audio_speaker.volume；拍照也以纯文本模拟，未完全复现视觉HTTP的JSON成功封装。这两项是测试设计不足。','- 最终模拟覆盖43个工具，本次真实目录为48个；未覆盖的5项为新闻、天气、音乐、habit_create和habit_list_manual。因此此前不能据43项报告宣称当前全部工具已经验证。','- 本次没有完整执行长期记忆写入、纠正、遗忘及跨重启召回；“你知道我最喜欢什么”未触发显式memory_search，不能据此认定记忆库丢失或正常。','- 音量100→90、亮度4→5档、明确两分钟提醒、闹钟创建与第二次删除均有设备执行证据；提醒交互窗口成功打开。本次未见异常WebSocket断开，结束时是正常空闲local_close。','', '## 完整对话','']
for n,t in enumerate(turns,1):
 lines += [f'### {n}．{t["time"]}','','用户：'+t['user'],'','设备回复：'+(' '.join(t['speech']) or '无最终播报；此轮随后被新消息接续。'),'','工具：'+json.dumps(t['tools'],ensure_ascii=False),'']
(R/'HARDWARE-TEST-REVIEW.md').write_text('\n'.join(lines),encoding='utf-8');(R/'issues.json').write_text(json.dumps([dict(id=i,priority=p,title=t,phenomenon=f,reason=r,certainty=c) for i,p,t,f,r,c,_ in issues],ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'report':str(R/'HARDWARE-TEST-REVIEW.md'),'issues':len(issues),'monitoring_active':status['active'],'user_confirmations':user_observations},ensure_ascii=False))
