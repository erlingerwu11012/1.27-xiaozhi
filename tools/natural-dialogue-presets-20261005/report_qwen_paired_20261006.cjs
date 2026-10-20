const fs=require('fs'),crypto=require('crypto'),assert=require('assert');
const root='docs/natural-dialogue-presets-20261005/';
const load=name=>JSON.parse(fs.readFileSync(root+name,'utf8'));
const original=load('qwen-paired-tool-results-20261006.json');
const pack=load('qwen-paired-tool-pack-20261006.json');
const resume=load('qwen-paired-semantic-resume-20261006.json');
const guard=load('qwen-paired-guard-regression-20261006.json');
const sorted=v=>Array.isArray(v)?v.map(sorted):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sorted(v[k])])):v;
const sha=v=>crypto.createHash('sha256').update(JSON.stringify(sorted(v))).digest('hex');
const {content_sha256:packHash,...body}=pack;
assert.equal(sha(body),packHash);
assert.equal(original.pack_sha256,packHash);
assert.equal(resume.original_pack_sha256,packHash);
assert(original.complete&&original.cases.length===840&&original.pairs.length===420);
assert(guard.passed&&guard.tests===124);
for(const row of pack.cases)assert.equal(sha({messages:row.initial_messages,tools:row.tools}),row.input_sha256);
for(const pair of original.pairs){
 const cases=original.cases.filter(r=>r.id===pair.id&&r.trial===pair.trial);
 assert(cases.length===2&&cases.every(r=>r.request_hashes[0]===pair.request_sha256&&r.input_sha256===cases[0].input_sha256));
 assert(pair.identical_initial_payload);
}
const rows=original.cases.map(r=>({...r,reviewed_pass:r.native_pass,review_notes:[]}));
for(const continuation of resume.cases){
 assert(continuation.continuation_pass&&continuation.reasoning_chars===0&&continuation.api_errors.length===0);
 const row=rows.find(r=>r.model===continuation.model&&r.id===continuation.id&&r.trial===continuation.trial);
 assert.deepEqual(row.steps[0].calls[0],continuation.unchanged_initial_call);
 if(!row.native_pass){
  assert.equal(row.model,'qwen3.8-flash');assert([31,35].includes(row.id));assert.equal(row.trial,1);
  row.reviewed_pass=true;row.review_notes=['提醒内容同义表达；不改原始调用，按冻结回执补完原请求后续，双方对称验证。'];
  row.reviewed_continuation=continuation;
 }
}
const live=original.models.map(model=>{
 const d=load('qwen-paired-live-'+model+'-20261006.json');
 d.cases=d.cases.map(r=>{
  const expectedZones=r.user.includes('分别几点')?['Europe/London','Asia/Tokyo']:r.user.startsWith('查询伦敦')||r.user.startsWith('伦敦那边')?['Europe/London']:r.user.startsWith('查询东京')||r.user.startsWith('东京的时间')?['Asia/Tokyo']:r.user.startsWith('查询上海')?['Asia/Shanghai']:[];
  const actual=r.tool_events.filter(e=>!e.blocked).map(e=>e.arguments.timezone);
  const coverage=expectedZones.length===0||expectedZones.every(z=>actual.includes(z));
  return {...r,reviewed_success:r.success&&coverage,review_notes:r.success&&!coverage?['自动脚本只核对已返回回执，漏检另一项请求；按遗漏工具操作计失败。']:[],expected_timezones:expectedZones};
 });
 d.reviewed_pass=d.cases.filter(r=>r.reviewed_success).length;
 d.native_positive=d.cases.filter(r=>r.expected_timezones.length&&r.primary_requests.length);
 return d;
});
assert.equal(live[0].system_sha256,live[1].system_sha256);
assert.equal(live[0].tool_catalog_sha256,live[1].tool_catalog_sha256);
const count=a=>({passed:a.filter(r=>r.reviewed_pass).length,total:a.length});
const pct=(p,n)=>(100*p/n).toFixed(2)+'%';
const groups=[...new Set(rows.map(r=>r.group))];
const summary=original.models.map(model=>{
 const r=rows.filter(r=>r.model===model),positive=r.filter(r=>r.expected.length),negative=r.filter(r=>!r.expected.length);
 const usage=r.flatMap(r=>r.usage),latency=r.map(r=>r.steps[0].first_ms).sort((a,b)=>a-b);
 return {model,...count(r),automatic_passed:r.filter(r=>r.native_pass).length,positive:count(positive),negative:count(negative),rounds:[1,2,3].map(trial=>({trial,...count(r.filter(c=>c.trial===trial))})),groups:groups.map(group=>({group,...count(r.filter(c=>c.group===group))})),all_three_passed:pack.cases.filter(c=>r.filter(x=>x.id===c.id).every(x=>x.reviewed_pass)).length,api_errors:r.filter(c=>c.api_errors.length).length,reasoning_chars:r.reduce((a,c)=>a+c.reasoning_chars,0),response_models:[...new Set(r.flatMap(c=>c.response_models))],input_tokens:usage.reduce((a,u)=>a+u.prompt_tokens,0),output_tokens:usage.reduce((a,u)=>a+u.completion_tokens,0),max_request_context_tokens:Math.max(...usage.map(u=>u.prompt_tokens)),first_decision_p50_ms:latency[Math.floor(latency.length*.5)],first_decision_p95_ms:latency[Math.floor(latency.length*.95)],failures:Object.fromEntries([...new Set(r.flatMap(c=>c.reasons))].map(reason=>[reason,r.filter(c=>!c.reviewed_pass&&c.reasons.includes(reason)).length]))};
});
assert.equal(summary[0].passed,415);assert.equal(summary[1].passed,292);
assert.equal(summary[0].positive.passed,299);assert.equal(summary[1].positive.passed,176);
assert.equal(live[0].reviewed_pass,11);assert.equal(live[1].reviewed_pass,9);
const pairs=original.pairs.map(p=>({...p,plus_pass:rows.find(r=>r.model===original.models[0]&&r.id===p.id&&r.trial===p.trial).reviewed_pass,flash_pass:rows.find(r=>r.model===original.models[1]&&r.id===p.id&&r.trial===p.trial).reviewed_pass}));
const pairedSummary=pairs.reduce((a,p)=>{const k=p.plus_pass?(p.flash_pass?'both_pass':'plus_only_pass'):(p.flash_pass?'flash_only_pass':'both_fail');a[k]=(a[k]||0)+1;return a;},{});
const review={created_date:'2026-10-07',test_fixture_date:'2026-10-06',pack_sha256:packHash,selection_rule:pack.selection_rule,winner:'qwen3.7-plus',changed_production:false,physical_test:false,identical_initial_api_payload_pairs:420,summary,paired_summary:pairedSummary,manual_corrections:[{model:'qwen3.8-flash',trial:1,id:31,reason:'取快递与拿快递同义，时间半小时后正确；保存原调用后补完双方后续流程。'},{model:'qwen3.8-flash',trial:1,id:35,reason:'站起来走走与起来活动一下同义，五分钟后正确；保存原调用后补完双方后续流程。'},{phase:'live MCP',model:'qwen3.8-flash',user:'帮我看一下现在伦敦和东京分别几点。',reason:'只查询伦敦，遗漏东京；自动通过改为复核失败。'}],guard,live,cases:rows,pairs};
fs.writeFileSync(root+'qwen-paired-reviewed-20261007.json',JSON.stringify(review,null,2));

const report=[];const line=s=>report.push(s);
line('# Qwen3.7 Plus 与 Qwen3.8 Flash：相同输入工具调用对照');
line('');line('报告生成：2026-10-07。主测试固定验收时钟为 2026-10-06 10:17:43（用于排除真实时间变化），不是设备当前时间。');
line('');line('结论：按“工具调用可靠性最高，相同时才比较价格”的规则，选择 **qwen3.7-plus**。两者差距明显，未触发价格决胜规则。没有切换正式默认模型，没有部署候选。');
line('');line('## 相同性证据');
line('');line('- 两模型各 140 条固定用例 × 3 轮 = 420 次，共 840 次。100 条需要工具，40 条不应调用工具，每轮重复同一套。');
line('- 同一最新平台提示词、相同用户人格、工具目录、历史、API 上游密钥及地域、温度 0.4、max_tokens 600、流式输出、enable_thinking=false、preserve_thinking=false；不启用 SDK 自动重试、二次润色或逐句语义校验。仅 model 字段不同。');
line('- 每一对首轮完整 API 请求（去掉 model）做 SHA256 核对：**420/420 完全相同**。工具 API 请求中包含结构化 tools；正文函数名不算调用。');
line('- 后续历史包含各模型自己产生的 tool_calls，不能要求输出相同；相同工具参数按同一确定回执规则处理。初始设备音量 50、亮度 80，时钟、随机结果、离线/超时/部分失败/排队/空回执固定。');
line('- 奇数用例沿用现有“腹黑、调皮、调侃”人格，偶数用例采用自然人格对照。每条用例两模型人格相同；没有修改真实用户的人格记录。');
line('- 先冻结提示词和评分规则再测试，三轮过程中不调提示词。真实 MCP 查询另测，不把变化的真实时间混入严格模型对照。');
line('- 主测试是原生调用决策对照，未借程序固定分支提升模型成绩；真实连接处理器验收才包含原有固定分支与工具回执保护。');
line('- 音量/亮度依实际 schema 限幅，120→100 合法；范围内数字不能擅自换成别的值。提醒时间、内容不允许乱补。');
line('- 冻结包哈希：`'+packHash+'`。报告脚本重新验证冻结包、140 条输入哈希及 420 对请求哈希。');
line('');line('## 复核后的调用决策结果');
for(const s of summary){
 line('');line('### '+s.model);
 line('');line('- 全部决策通过：**'+s.passed+'/'+s.total+'（'+pct(s.passed,s.total)+'）**。包含应调用和不应调用两类。');
 line('- 需要调用工具的操作请求通过：**'+s.positive.passed+'/'+s.positive.total+'（'+pct(s.positive.passed,s.positive.total)+'）**。必须完整满足名称、参数、依赖顺序和全部动作；失败后重复写入也不通过。');
 line('- 不应调用场景通过：'+s.negative.passed+'/'+s.negative.total+'（'+pct(s.negative.passed,s.negative.total)+'）。');
 line('- 三轮通过数：'+s.rounds.map(r=>r.passed+'/'+r.total).join('、')+'。140 个不同用例中，三轮均通过 '+s.all_three_passed+' 个。');
 line('- 接口错误 '+s.api_errors+' 次，思考输出 '+s.reasoning_chars+' 字符；API 返回模型标识 '+s.response_models.join(', ')+'。');
 line('- 自动原分数 '+s.automatic_passed+'/'+s.total+'；人工复核分数如上。');
 line('- 失败类别：'+Object.entries(s.failures).map(([k,v])=>k+'='+v).join('；')+'。');
}
line('');line('两者同一对请求中：共同通过 '+pairedSummary.both_pass+' 次，仅 Plus 通过 '+pairedSummary.plus_only_pass+' 次，仅 Flash 通过 '+pairedSummary.flash_only_pass+' 次，共同失败 '+pairedSummary.both_fail+' 次。总体相差 '+(100*(summary[0].passed-summary[1].passed)/420).toFixed(2)+' 个百分点。');
line('');line('## 人工复核透明记录');
line('');line('Flash 原自动分数 290/420，复核为 292/420：第一轮第 31 条“拿快递”与“取快递”、第 35 条“起来活动一下”与“站起来走走”语义等价，时间参数正确。保留首次原输出，没有重抽、更改参数或挑好结果；双方分别接续自己的原调用，发送原冻结回执，四次后续均通过。原始 JSON 保持不变，补充记录独立保存。');
line('');line('其他参数失败均逐条检查。例如 habit_create 漏传 advance_minutes 不能当作“不提前提醒”，因为真实目录声明默认提前 2 分钟；温哥华请求传 America/Los_Angeles 不等于指定的 America/Vancouver，本次保留准确地区参数标准。即使放宽这两次同 UTC 偏移案例，也不改变模型排序。');
line('');line('## 真实 MCP 与保护层');
for(const d of live){
 line('');line('- '+d.model+'：复核 '+d.reviewed_pass+'/'+d.cases.length+'；其中需要模型原生选择工具的正向查询 '+d.native_positive.filter(r=>r.reviewed_success).length+'/'+d.native_positive.length+'。包含固定程序分支，不能把 11 条都称作纯模型调用。');
}
line('');line('真实查询使用正式 ConnectionHandler、ToolManager 和实际 MCP 服务，只查询时间；没有设备连接，没有硬件设置、拍照或真实提醒写入。两次实际测试 system 和工具目录哈希相同。Flash 的原自动分数 10/11，复核 9/11：一条沿用旧伦敦时间未重新查询，另一条同时问两城却只查伦敦。');
line('');line('原有回执、去重、权限、schema 与限幅保护候选：124/124 回归通过。它能保护所覆盖的执行约束，不能据此声称所有自然语言都理解正确。');
line('');line('## 明确失败原文');
for(const [model,id,trial] of [['qwen3.8-flash',16,1],['qwen3.8-flash',51,1],['qwen3.8-flash',110,1],['qwen3.7-plus',78,1],['qwen3.7-plus',79,2],['qwen3.7-plus',136,3]]){
 const r=rows.find(r=>r.model===model&&r.id===id&&r.trial===trial);
 line('');line('### '+model+' · 用例 '+id+' · 第 '+trial+' 轮');
 line('');line('用户：'+r.user);line('');line('预期：`'+JSON.stringify(r.expected)+'`。');
 for(const [i,s] of r.steps.entries()){
  line('');line('模型第 '+(i+1)+' 步原文：');line('');line('```text');line(s.text||'（正文为空）');line('```');
  line('');line('结构化调用：');line('');line('```json');line(JSON.stringify(s.calls,null,2));line('```');
 }
}
line('');line('## 限制与上线建议');
line('');line('- 这些是定向案例通过率，不是线上所有请求的总体概率，也不是完整语音实机验收。三轮重复同一套，不能按 420 个完全不同、独立案例解释。');
line('- 主要排名是工具调用决策，回执正文忠实度独立观察。两模型空回执时都有“已调好”的错误正文；Plus 的第 138 条三轮都出现，Flash 第 138 条的两次正确调用后也出现。**不能取消原有工具回执保护**，也不能把 98.81% 说成所有对话均正确。');
line('- Plus 仍有 5 个调用决策失败：缺认人能力却拍照 3 次、调用本次目录不存在的 reminder_get_current 1 次、部分失败后擅自重复亮度设置 1 次。后两类应由工具目录校验与去重保护拒绝；认人能力边界仍需补强。');
line('- 推荐主模型 qwen3.7-plus、非思考模式、温度 0.4，加原有工具执行与回执保护。当前 Flash 不满足“可靠性相同才选更便宜”的条件。');
line('- 本次没有换正式默认模型、没有改用户人格、没有上线；生产 HEAD 和已有未提交状态保持不变。');
line('');line('## 文件');
line('');line('- `qwen-paired-tool-pack-20261006.json`：完整冻结输入、提示词、工具目录、预期和哈希。');
line('- `qwen-paired-prompt-20261006.txt`：现有人格下实际发送的完整提示词。');
line('- `qwen-paired-tool-results-20261006.json`：不可覆盖的 840 条原始模型输出。');
line('- `qwen-paired-semantic-resume-20261006.json`：2 条同义表达的双方后续原文。');
line('- `qwen-paired-reviewed-20261007.json`：人工复核标签与总结，不改原始记录。');
line('- `QWEN_PAIRED_FULL_TRANSCRIPTS_20261007.md`：全部 420 对完整原文、工具调用与固定回执，另含真实 MCP 原文。');
fs.writeFileSync(root+'QWEN_PAIRED_TOOL_REPORT_20261007.md',report.join('\n')+'\n');

const transcript=[];const add=s=>transcript.push(s);
add('# 相同提示词 Qwen 对照：全部 420 对原始对话');add('');add('原始测试 840 条，140 个用例各 3 轮。下列空正文、无调用、错误参数、提前停止均如实保留。模型系统提示词及结构化 tools 的完整内容见冻结包；不在每条重复同样的系统全文。2 条语义误判的后续补充明确标记，不冒充原采样。');
for(const trial of [1,2,3])for(const source of pack.cases){
 add('');add('## 第 '+trial+' 轮 · 用例 '+source.id+' · '+source.group);add('');add('人格：'+source.persona);add('');
 if(source.history?.length){add('历史原文：');add('');add('```json');add(JSON.stringify(source.history,null,2));add('```');add('');}
 add('用户：'+source.user);add('');add('预期：`'+JSON.stringify(source.expected)+'`');
 for(const model of original.models){
  const r=rows.find(r=>r.model===model&&r.id===source.id&&r.trial===trial);
  add('');add('### '+model+' · '+(r.reviewed_pass?'调用决策通过':'调用决策失败'));add('');
  if(r.review_notes.length)add('人工复核：'+r.review_notes.join('；')+'\n');
  let eventIndex=0;
  for(const [i,s] of r.steps.entries()){
   add('模型第 '+(i+1)+' 步正文原文：');add('');add('```text');add(s.text||'（正文为空）');add('```');add('');
   add('真实结构化 tool_calls（仅记录，不执行真实副作用）：');add('');add('```json');add(JSON.stringify(s.calls,null,2));add('```');add('');
   const ev=[];
   for(const call of s.calls){
    const event=r.events[eventIndex];
    if(event&&event.name===call.name&&event.raw_arguments===call.arguments){ev.push(event);eventIndex++;}
   }
   if(ev.length){add('已匹配调用的固定隔离回执及原保护层回复：');add('');add('```json');add(JSON.stringify(ev,null,2));add('```');add('');}
  }
  if(r.reasons.length)add('原自动判定原因：'+r.reasons.join('、')+'。\n');
  if(r.reviewed_continuation){add('同义表达复核后接续原始调用的补充记录：');add('');add('```json');add(JSON.stringify(r.reviewed_continuation,null,2));add('```');add('');}
 }
}
add('');add('# 真实 MCP 经正式处理器验收');
for(const d of live){add('');add('## '+d.model);for(const r of d.cases){add('');add('### 用户：'+r.user);add('');add('最终播报原文：');add('');add('```text');add(r.spoken);add('```');add('');add('真实工具事件与原评分、复核评分：');add('');add('```json');add(JSON.stringify(r,null,2));add('```');}}
fs.writeFileSync(root+'QWEN_PAIRED_FULL_TRANSCRIPTS_20261007.md',transcript.join('\n')+'\n');
console.log(JSON.stringify({winner:review.winner,summary,live:live.map(d=>({model:d.model,passed:d.reviewed_pass,total:d.cases.length})),paired_summary:pairedSummary,pack_sha256:packHash},null,2));
