import json,re,sys,hashlib
from pathlib import Path
p=Path(__file__).parent;d=p/'frozen-20261008-budget-delta';sys.path.insert(0,str(d));import bootstrap
from test_protocol import raw_name
r=json.loads((p/'budget-release-report.json').read_text());out=p/'delivery';out.mkdir(exist_ok=True)
private=json.loads((p/'private-backup/runtime-config.json').read_text());device=json.loads((p/'private-backup/device-config.json').read_text());values=set()
def collect(x):
 if isinstance(x,dict):
  for k,v in x.items():
   if isinstance(v,str) and len(v)>=8 and re.search(r'api.?key|secret|password|token|account.?id|user.?id|agent.?id|device.?id',k,re.I):values.add(v)
   collect(v)
 elif isinstance(x,list):
  for v in x:collect(v)
collect(private);collect(device)
values.update(['ac:a7:04:fd:20:2c','ac:a7:04:fd:20:5c'])
def clean(x):
 if isinstance(x,dict):return {k:clean(v) for k,v in x.items() if not re.search(r'authorization|headers|api.?key|secret|password|signature|^_meta$|account.?id|agent.?id|user.?id',k,re.I)}
 if isinstance(x,list):return [clean(v) for v in x]
 if isinstance(x,str):
  for v in sorted(values,key=len,reverse=True):x=x.replace(v,'[已隐去私人标识]')
  return x
 return x
r=clean(r)
for t in r['catalog']:
 if t['source']=='device_mcp':t['raw_name']=raw_name(t['name']);t['raw_name_basis']='firmware-verified catalog mapping and loopback tools/list; not a new live hardware inventory'
(out/'test-report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
(out/'tool-coverage.json').write_text(json.dumps(r['catalog'],ensure_ascii=False,indent=2))
conv=(p/'budget-conversations.md').read_text()
for v in sorted(values,key=len,reverse=True):conv=conv.replace(v,'[已隐去私人标识]')
def clean_block(match):
 try:return '```json\n'+json.dumps(clean(json.loads(match.group(1))),ensure_ascii=False,indent=2)+'\n```'
 except ValueError:raise RuntimeError('invalid_conversation_json')
conv=re.sub(r'```json\n(.*?)\n```',clean_block,conv,flags=re.S)
(out/'conversations.md').write_text(conv)
(out/'original-failures.json').write_text(json.dumps(r['previous_failures'],ensure_ascii=False,indent=2))
(out/'final-wire-evidence.json').write_text(json.dumps(clean(json.loads((d/'full-message-evidence.json').read_text())),ensure_ascii=False,indent=2))
lines=['# 全工具 Harness 验收与上线记录','','版本：`'+r['code_hash']+'`。','模型仍为 Qwen3.7-Plus，非思考、温度 0.4；人格、官方服务选择与 One-API 计费配置保持一致。','','## 验收结果','','| 项目 | 结果 |','|---|---|','| 当前已审核可用工具 | 43 项 |','| 合法可完成目标 | 520/520 |','| 常用操作（含复杂及保留场景） | 210/210 |','| 单工具合法样本 | 416/416；每项至少8条 |','| 否定、引用、缺参等单工具场景 | 172/172 |','| 复杂多轮场景 | 60/60 |','| 保留与独立补充场景 | 74/74 |','| 已接受但未证明最终完成 | 32条，单列并如实播报阶段 |','| 未请求写入、重复写入、回执播报不一致 | 本次验收未发现 |','| 必需工具召回 | 416/416 |','| 普通操作匹配对比 | 34组：P95 3.43秒，基线3.97秒 |','| 必要依赖匹配对比 | 9组：P95 4.51秒，基线4.78秒 |','| 正常请求次数增加的样本 | 0 |','| 最终源码单元/预算/协议/现有回归 | 490项通过 |','| 最终真实模型到软件WebSocket/MCP设备完整链路 | 7条通过 |','','## 证据与费用口径','','最终有效候选记录为722条，其中174条在最终源码上调用真实模型；548条使用之前真实模型录制的决策，在最终源码上完成执行回放。回放不消耗模型API，也不等同于用最终提示词重新询问模型。另有43条相同输入的原链路对照。','原全量重复方案因用户费用要求停止，改为全工具覆盖一次、修复组定向回归及独立样本；未降低成功率和安全门槛。最终版本没有重新跑完整套真实模型测试，不能把此处100%理解为未来所有自然语言都必然成功。','本次恢复后的真实模型请求累计990次；连同暂停前保留记录，累计1841条对话测试，均在本轮1000请求/2000记录上限内。此前开发阶段发生的费用不包含在990次中。未核算实际人民币账单。','原失败记录全部保留。旧版候选8条、基线4条失败均保存在 original-failures.json；有两项旧评分口径纠正，见 test-report.json 的 oracle_corrections；未删除样本。','','## 工具覆盖','','目录包含35项设备MCP、5项服务插件、3项服务MCP。两项缺少可信绑定的旧习惯入口保持停用。当前未启用的设备IoT及MCP接入点未擅自启用。以后新增目录项可发现，但未审核写操作默认不可执行。','','| 工具 | 来源 | 合法通过率 | 写操作 |','|---|---|---|---|']
for t in r['catalog']:
 if t['availability']=='available':
  v=r['chains']['candidate']['per_tool'][t['name']];lines.append(f"| `{t['name']}` | {t['source']} | {v['passed']}/{v['n']} | {'是' if t['write'] else '否'} |")
lines+=['','## 已实现的行为','','- 模型输出结构化决策，经服务端严格校验后才可执行；正文伪造调用不能进入执行器。','- 完整用途索引与最多16项首轮Schema，补齐依赖，可扩展已审核工具；关键词分数只辅助召回。','- 相对设置连续完成查询、计算、设置、核验；中间状态不直接播报。百分数、最大、中文数字等均纳入测试。','- 闹钟、定时提醒、便签与当前卡片操作分别验证，缺参和歧义先澄清。','- 权限、身份、连接与工具目录版本由服务端核对；本轮目标之外的写操作拒绝执行。','- 操作账本去重；结果未知不擅自重发创建/删除。最多一次纠正，8次工具执行、4次正常决策另加一次纠正、总时限90秒。','- 最终语音、字幕与历史统一根据操作结果生成；排队、已接受、失败、未知与已完成分别表述。','- 普通聊天保留用户人格，不增加二次润色模型。','','## 正式部署与回滚','','正式域名：www.realecho.cn。服务文件在原目录覆盖，未建立并行V2产品。','稳定启动与回滚程序：`/root/prjs/releases/tool-harness-20261008/rollout.py`。','私有备份：`/root/prjs/releases/tool-harness-20261008/backup`（仅服务器保留）。','观察记录：`/root/prjs/releases/tool-harness-20261008/observation.json`。','部署状态：`/root/prjs/releases/tool-harness-20261008/deployment-state.json`。','监听就绪后才切换nginx，再停止旧进程；旧8006内部入口通过本机代理保持认证兼容。','必要时回滚：`/root/miniconda3/envs/xiaozhi-esp32-server/bin/python /root/prjs/releases/tool-harness-20261008/rollout.py rollback`。回滚保留操作账本；检测到其他工作区后续改动时拒绝覆盖。','','## 尚未证明的项目','','本轮无实机配合。未证明设备真实物理音量/亮度改变、实际拍照、存储写入、提醒播放、声纹身份或固件迁移已经通过。软件设备使用实际Schema和已核对的旧固件回执格式。生产检查仅验证健康、认证、路由和配置，不进行真实设备写入。','30分钟观察完成状态见 deployment-status.json；观察期间没有业务流量时，健康通过不能替代真实工具使用验收。']
(out/'README.md').write_text('\n'.join(lines))
(out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n' for f in sorted(out.iterdir()) if f.is_file() and f.name!='SHA256SUMS.txt'))
print(json.dumps({'files':sorted(f.name for f in out.iterdir()),'export_private_config':False,'real_model_requests':0}))
