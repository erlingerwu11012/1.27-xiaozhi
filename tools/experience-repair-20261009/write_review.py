from pathlib import Path
import tarfile,json,hashlib,zipfile
S=Path(__file__).parent;O=S/'evidence';O.mkdir(exist_ok=True)
with tarfile.open(S/'review-evidence.tgz') as t:
 for m in t.getmembers():
  p=(O/m.name).resolve();assert p.is_relative_to(O.resolve()) and m.isfile(),m.name
  p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.extractfile(m).read())
s=json.loads((O/'review-summary.json').read_text(encoding='utf-8'));f=json.loads((S/'firmware-package-result.json').read_text(encoding='utf-8'))
def rows(name):
 p=O/name;return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []
a=rows('final-results.jsonl');focus=rows('postfix-focused-results.jsonl');facts=rows('fact-fix-focus-results.jsonl');fails=[x for x in a if x['errors']]
lines=['# 对话、工具结果与记忆修复：候选审查记录','', '状态：**未上线，未刷机，尚未通过最终全量验收。**','', '正式服务源码漂移检查为空，PM2 的 xiaozhi-server、manager-api 均在线。本报告区分每次候选版本，不将不同版本的测试拼成一次达标验收。','', '## 本轮完成的修改','', '- 有效用户请求与普通监听编号解耦；保留真正打断、身份变化、连接替换的失效检查。','- 统一核对工具回执、目标值及业务状态；相对调节中间查询不单独播报。修复渲染模式被当作亮度、第二档被当作相对调节、跨句相对幅度丢失。','- 当前卡片的跳过、静音、稍后提醒分别验证，禁止错误新建提醒；查询复用本轮真实回执，避免额外模型循环。','- 记忆查询使用带来源和稳定标识的单条事实；纠正、遗忘核对隔离管理 API 与数据库，并验证重启后状态。历史污染私有待审清单共4项，默认未应用隔离，未删除真实用户原文。','- 摄像头失败原因保留并转换成中文；Python 字典和原始 JSON 不得播报。视觉上游同步工作移到后台线程并设超时。','- 按同一说话人保留最近原话，明确未被用户更新的状态不能自行推进。用户人格、主模型和计费配置未改。','', '## 验收证据与限制','', '- 最新完整批次在217条处暂停：208条按原自动断言通过，9条需处理；该批不是最终通过证据。完整失败原文见下文和 JSONL。','- 修复后的21条定向复测：19条按原断言通过；1条外卖状态无依据推断；1条卡片查询实际读到正确结果，但重复查询使“恰好一次结果”的断言失败。后者同时反映冗余模型循环，已修复并以真实 MCP 软件连接验证单次查询。','- 进一步事实策略调整后的5轮真实聊天全部通过；这是定向样本，不能代替独立保留集或完整最终验收。','- 49项相关回归通过；5项生命周期回归通过；178项较早相关回归通过。最早388项批次保留4项失败原文，部分是本轮行为变更导致的旧断言，不能宣称原批次全通过。','- Java真实隔离 MySQL 测试28项通过，实际 HTTP 管理 API 及重启持久性测试11项通过。','- 视觉 HTTP 验证：401、会话错误403、慢模型下事件循环仍响应；2次真实视觉模型上传/追问均200且正确识别合成蓝色图片。','- 实际成功生成3段语音 WAV。TTS预算计数6包含3次配置缺失、网络调用前失败的保守扣数。','- 视觉凭据固件主机测试和ESP32-S3完整编译通过；程序4,891,168字节，分区剩余286,176字节，15个资源文件校验通过。','- 硬件未参与。没有证明真实摄像头采集、扬声器、物理亮度、存储迁移或实际Wi-Fi稳定性。','- 最终代码上的至少240条真实模型测试、正式部署及30分钟观察尚未完成。不能根据局部通过上线。','', '## 累计预算与费用','']
for k,title in [('case','测试条目'),('model','主模型HTTP请求'),('tts','TTS预算计数'),('vision','视觉模型请求')]:
 b=s['budget'][k];lines.append(f'- {title}：{b["used"]} / {b["limit"]}。')
u=s['model_usage'];lines+= [f'- 已取得主模型token：输入{u["prompt_tokens"]:,}，输出{u["completion_tokens"]:,}，合计{u["total_tokens"]:,}。','- 没有可靠关联每条测试与网关扣费交易ID，因此没有把同账号其他业务费用计为测试费用，也没有虚报金额。','- 主模型剩余67次，无法完成修复后至少240条真实模型测试。已提出是否提高上限的预算问题；未获得同意前保持600次硬上限，不追加完整付费批次。','', '## 暂停批次的失败原文','']
for x in fails:
 lines +=[f'### 用例 {x["case"]["id"]}', '',f'用户：{x["case"]["query"]}', '',f'实际回复：{x.get("speech","")}', '', '自动断言：'+', '.join(x['errors']), '']
 for r in x.get('outcome',{}).get('results',[]):lines.append(f'- 工具 `{r["tool"]}`；状态 `{r["state"]}`；参数 `{json.dumps(r["arguments"],ensure_ascii=False)}`。')
 lines.append('')
lines += ['## 最新五轮事实保持对话','']
for x in facts:lines +=['用户：'+x['case']['query'],'','助手：'+x.get('speech',''),'', '结果：'+('通过' if not x['errors'] else ','.join(x['errors'])),'']
lines += ['## 交付与恢复','',f'- 固件候选包：[experience-repair-20261009.zip](E:/github/github_code/all/4.30/releases/experience-repair-20261009.zip)。SHA256：`{f["sha256"]}`。','- 默认使用包内 Upgrade-Preserve.ps1，先备份和校验。new-device-reset镜像会清空数据，不是普通升级方式。用户自行烧录。','- 本轮只修改隔离候选服务；因此没有执行生产回滚。原服务仍运行。备份位于服务器 `/root/prjs/releases/experience-repair-20261009/backup`，包含私有源码、配置和数据库备份；不随证据包导出。','- 17项 Python 候选源码清单与SHA256见 review-summary.json；Java候选源码另附。固件编译包含工作区原有 application.cc TTS中断改动，已在包内说明。','- 完整模拟对话、决策、调用参数、真实协议回执、状态及回查见 evidence 目录内 JSONL。记录均来自合成账号和软件设备；密钥和真实用户数据库不在包内。','- 记忆审查与可撤销隔离脚本 memory_quarantine.py 默认scan；未经批准记录不会应用隔离。后续回滚也会拒绝覆盖更新过的原文或较新的遗忘决定。','']
(S/'TEST-REVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
dest=Path('releases/experience-repair-evidence-20261009.zip')
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
 z.write(S/'TEST-REVIEW.md','TEST-REVIEW.md')
 for p in O.rglob('*'):
  if p.is_file():z.write(p,'evidence/'+p.relative_to(O).as_posix())
 for p in (S/'java').glob('*.java'):z.write(p,'java/'+p.name)
 z.write(S/'migration.sql','migration.sql')
print(json.dumps({'report':str((S/'TEST-REVIEW.md').resolve()),'evidence_zip':str(dest.resolve()),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'budget':s['budget']},ensure_ascii=False))
