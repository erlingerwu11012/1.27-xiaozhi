/* Offline reporting only. Preserves all upstream replies and raw evaluator flags. */
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const out = path.resolve('docs/natural-dialogue-presets-20261005');
const read = name => JSON.parse(fs.readFileSync(path.join(out,name),'utf8').replace(/^\uFEFF/,''));
const write = (name,value) => fs.writeFileSync(path.join(out,name),typeof value==='string'?value:JSON.stringify(value,null,2),'utf8');
const data = read('prompt-only-comparison.json');
const formal = read('prompt-only-formal-verification.json');
const guides = read('prompt-only-guidance-snapshot.json');
const variants = ['current','prompt_only'];
const titles = ['书架与报告','展览与买票','电饭煲与做饭','吉他与琴弦','约饭与餐厅','落地灯与椅子','演示文稿进度','加班与话题切换','杯子与拼图','黄油与游泳'];
const names = {current:'当前线上提示词',prompt_only:'新提示词（仅替换交谈指导）'};
const expected = {
  0:'书架已发货、未收到；报告上周完成一半，昨天只改标题。',
  1:'这周末不去，下周再考虑，尚未确定；票明确没有买。',
  2:'电饭煲订单缺货取消、没有发货；昨晚只切了菜，没有下锅。',
  3:'曲子前半能弹，后半未练；琴弦刚买，未发货、未更换。',
  4:'朋友已明确周五没空，未改约其他日期，未约成、未订餐厅。',
  5:'灯最新已揽收、未收到；椅子早已送到。',
  6:'十页中正文真正写好三页，还剩七页。',
  8:'杯子缺货取消、未发货；拼图只有边框完成、中间未拼。',
  9:'明天游泳计划取消；黄油仅拿出，未称重、未打发。'
};
const failedRecall = {
  'current/natural/1':'回答末尾称全程没提过买票；用户在本段明确说过没有买票。',
  'current/natural/4':'把朋友已说周五没空回退成未确认有没有空。',
  'current/natural/6':'正文三页回退成两页；剩余七页答成八页，另猜测有两页空白。',
  'current/existing-playful/0':'最新已发货回退成还没发货。',
  'current/existing-playful/1':'前句答没买票，后句却说票买没买没影；明确事实变得不确定。',
  'current/existing-playful/2':'缺货取消回退成后天发货。',
  'prompt_only/natural/4':'把朋友已说周五没空回退成未确认有没有空。',
  'prompt_only/existing-playful/0':'最新已发货回退成还没发货。',
  'prompt_only/existing-playful/5':'最新已揽收回退成还没被快递收走。'
};
assert(data.completed && data.calls===400 && data.dialogues.length===40);
assert(data.dialogues.every(d=>d.turns.length===10));
assert(formal.source_hashes_unchanged);
const percentile = (xs,p) => [...xs].sort((a,b)=>a-b)[Math.max(0,Math.ceil(xs.length*p)-1)];
const stats = {};
const recall = [];
const mcp = {};
for(const v of variants){
  const ds = data.dialogues.filter(d=>d.variant===v), rows=ds.flatMap(d=>d.turns);
  const selected = ds.filter(d=>d.scenario!==7).map(d=>{
    const t=d.turns[(d.scenario===5||d.scenario===6)?8:9];
    return {id:d.id,turn:t.turn,user:t.user,assistant:t.assistant,expected:expected[d.scenario],passed:!failedRecall[d.id],reason:failedRecall[d.id]||'关键状态完整，回答未与本段明确事实冲突。'};
  });
  assert(selected.length===18); recall.push(...selected);
  stats[v] = {
    turns:rows.length, pipeline_completed:rows.filter(r=>r.pipeline_completed).length,
    primary_requests:rows.reduce((n,r)=>n+r.request_count,0),
    primary_first_text_p50_ms:percentile(rows.map(r=>r.first_primary_text_ms).filter(x=>x!==null),.5),
    primary_first_text_p95_ms:percentile(rows.map(r=>r.first_primary_text_ms).filter(x=>x!==null),.95),
    first_tts_enqueue_p50_ms:percentile(rows.map(r=>r.first_tts_enqueue_ms).filter(x=>x!==null),.5),
    first_tts_enqueue_p95_ms:percentile(rows.map(r=>r.first_tts_enqueue_ms).filter(x=>x!==null),.95),
    mean_reply_chars:Math.round(rows.reduce((n,r)=>n+r.assistant.length,0)/rows.length),
    truncated_responses:rows.filter(r=>r.finish_reasons.includes('length')).length,
    chat_tool_proposals:rows.reduce((n,r)=>n+r.tool_proposals.length,0),
    chat_tool_proposal_turns:rows.filter(r=>r.tool_proposals.length).length,
    blocked_chat_tool_cases:ds.flatMap(d=>d.turns.filter(r=>r.tool_proposals.length).map(r=>({id:d.id,turn:r.turn,user:r.user,proposals:r.tool_proposals,assistant:r.assistant}))),
    strict_recall_passed:selected.filter(r=>r.passed).length,strict_recall_total:18
  };
  const raw=read(`prompt-only-mcp-${v}.json`);
  const cases=raw.cases.map((r,index)=>({...r,index:index+1,raw_automatic_pass:r.success,
    reviewed_pass:r.success && !(v==='prompt_only' && index===8),
    review_reason:index<6 && !r.success?'最新时间查询未产生本轮真实工具调用；沿用历史时间不满足验收。':
      v==='prompt_only' && index===8?'正文输出调用标签，实际事件为空；能力缺失也没有解释。原自动判断漏检，本报告记为失败。':'实际调用与回执一致，或准确解释能力缺失/没有执行用户否定的操作。'}));
  assert(cases.length===11);
  mcp[v]={cases,passed:cases.filter(r=>r.reviewed_pass).length,total:11,
    fresh_query_passed:cases.slice(0,6).filter(r=>r.reviewed_pass).length,fresh_query_total:6,
    real_tool_calls:cases.reduce((n,r)=>n+r.tool_events.length,0)};
}
const examples = [
 ['prompt_only/natural/0',5,'忽略明确反馈','用户已禁止“慢慢来”；回答仍劝慢慢来，并编造书在箱子里。'],
 ['prompt_only/natural/2',1,'编造物流进度','用户说后天发货；回复改成两天收到，发货与到货不是一回事。'],
 ['prompt_only/natural/3',9,'回退已更新事实','琴弦已经买了，回复却说还没买。'],
 ['prompt_only/natural/5',5,'内部格式泄漏','直接输出用户原话标签和问题，没有正常作答。'],
 ['prompt_only/natural/8',7,'内部叙述泄漏','以“用户纠正说”代替直接回应。'],
 ['prompt_only/existing-playful/0',7,'示例内容串入','报告问题回复成今天动了字幕，并给用户未要求的安排。'],
 ['prompt_only/existing-playful/5',9,'回退已更新事实','灯已揽收，最终总结仍说还没被快递收走。'],
 ['prompt_only/existing-playful/9',6,'无依据声称营业','没有查过具体泳池，仍称泳池白天才开。'],
 ['current/natural/3',9,'内部格式泄漏','回答暴露Python列表形式的文本内容。'],
 ['current/existing-playful/5',1,'混淆对象与状态','灯未收件，却声称灯已派上用场，还引入未提及的新椅子状态。']
].map(([id,turn,category,reason])=>{const d=data.dialogues.find(d=>d.id===id);return{id,turn,category,reason,...d.turns[turn-1]};});
const audit={date:'2026-10-06',method:'真实生产处理器；相同100个输入，两个人格，两版提示词。事实子集逐条人工审查，全文回答出现已知事实冲突也判失败。未将400轮技术完成率当作自然聊天通过率。',stats,recall,mcp,examples,
  overall_quality_passed:false,deployed:false,formal_verification:formal,
  limitations:['单次配对实验，模型有随机性，不能据此承诺总体成功率。','事实子集每版18题，不能代替200轮聊天整体评分。','聊天测试使用固定2026-10-03零点上下文，两版相同；MCP时间是真实10月6日服务结果。','真实默认上游模型，测试输出上限450 tokens；未出现length截断。','聊天中的工具建议被记录并阻止执行；时间MCP在独立阶段真实执行。','没有设备ASR、实际语音播放、音量、亮度、拍照、提醒验收。']};
write('prompt-only-reviewed-results.json',audit);
let full='# 新提示词单独替换：完整逐轮对照\n\n测试日期：2026-10-06；真实默认模型 qwen3.8-flash，temperature=0.4。100个不同输入 × 两个人格 × 两版 = 400轮回复。未启用逐句校验、聊天重试、证据注入、答案裁剪或二次润色；原有操作和回执保护保留。\n\n原文完整保留；系统测试拦截消息也保留。这些是合成场景，不是客户对话。\n';
for(const p of ['natural','existing-playful'])for(let scene=0;scene<10;scene++){
  const a=data.dialogues.find(d=>d.variant==='current'&&d.persona===p&&d.scenario===scene),b=data.dialogues.find(d=>d.variant==='prompt_only'&&d.persona===p&&d.scenario===scene);
  full+=`\n## ${p==='natural'?'随和自然人格':'原有调皮人格'} · ${scene+1}. ${titles[scene]}\n\n人格原文：${a.persona_prompt}\n`;
  for(let i=0;i<10;i++){
    assert(a.turns[i].user===b.turns[i].user);
    full+=`\n### 第 ${i+1} 轮\n\n用户：${a.turns[i].user}\n\n当前：\n\n${a.turns[i].assistant}\n\n新提示词：\n\n${b.turns[i].assistant}\n`;
    for(const d of [a,b])if(d.turns[i].tool_proposals.length)full+=`\n${names[d.variant]}提出工具调用（聊天阶段仅记录、未执行）：\n\n\`\`\`json\n${JSON.stringify(d.turns[i].tool_proposals,null,2)}\n\`\`\`\n`;
  }
}
full+='\n## MCP完整原文与执行记录\n';
for(const v of variants)for(const r of mcp[v].cases)full+=`\n### ${names[v]} · 工具第 ${r.index} 题 · ${r.reviewed_pass?'通过':'失败'}\n\n用户：${r.user}\n\n回答：${r.spoken}\n\n复核：${r.review_reason}\n\n真实工具事件：\n\n\`\`\`json\n${JSON.stringify(r.tool_events,null,2)}\n\`\`\`\n`;
write('PROMPT_ONLY_FULL_TRANSCRIPTS_20261006.md',full);
let report='# 新提示词＋原有工具回执保护：测试报告\n\n结论：当前候选尚不适合上线。新提示词在事实子集上有改善，但仍编造细节、忽略明确反馈、串入示例与内部标签；工具阶段也未全部通过。当前线上版本同样存在问题，不能把维持线上理解为它已经通过验收。\n\n## 本次到底改了什么\n\n只在隔离测试进程中替换交谈指导段，使用生产ConnectionHandler、原有工具定义与回执保护。模型仍是 qwen3.8-flash，温度0.4。用户人格未改；没有逐句校验、聊天重试、证据注入、输出裁剪或二次模型。两个实际指导段见 prompt-only-guidance-snapshot.json。\n\n## 可复核结果\n';
for(const v of variants){const s=stats[v],m=mcp[v];report+=`\n${names[v]}：200/200轮处理完成；首段文字交给TTS队列的中位数 ${s.first_tts_enqueue_p50_ms} ms，P95 ${s.first_tts_enqueue_p95_ms} ms；平均回复 ${s.mean_reply_chars} 字符。事实子集严格通过 ${s.strict_recall_passed}/18；MCP人工复核通过 ${m.passed}/11，其中需本轮实际查时间的题 ${m.fresh_query_passed}/6。实际时间工具调用 ${m.real_tool_calls} 次。聊天阶段提出 ${s.chat_tool_proposals} 次工具调用，全部被测试拦截器阻止执行。\n`;}
report+='\n“200/200”只表示拿到了回复；不是自然程度合格率。事实子集检查最新状态和全文冲突，包含每个人格9道明确回忆题；不存在人工审核通过的全400轮质量百分比。\n\n## 明确失败\n';
for(const e of examples)report+=`\n- ${e.id} 第${e.turn}轮：${e.reason}\n  - 用户：${e.user}\n  - 模型原文：${e.assistant.replace(/\n/g,' ')}\n`;
report+='\n## 工具保护的边界\n\n两版各5次真实时间工具执行都有真实回执，输出与回执直接渲染一致。它证明原有回执链路仍工作，但不能保证模型必定发起正确调用。新提示词的双城市查询没有本轮调用；缺少设备状态能力时，仅在正文输出 `[调用: get_device_status]`，实际上没有执行。原自动断言把这一条漏判为通过，本报告按失败更正，保留原始JSON不覆盖。两版各9/11通过，不能对外声称工具已经全部可用。\n\n明确时间请求有些由已有确定性路由直接处理，原始 primary_requests 为空；口语请求才经过默认模型选择。因此这里没有将所有成功工具题都算成大模型调用成功。仅测试服务MCP时间能力与缺失能力拒绝，没有验收真实硬件操作。\n\n## 提示词与边界建议\n\n可以保留“没有二次润色、原工具保护”的方向，但本次新提示词不能直接上线。下一步应先补工具调用与缺失能力的程序判断，正文中的调用标签不能作为执行成功；提示词示例应减少与用户场景相似的具体物品和进度，避免照抄串入。事实反复回退则需要明确的状态记录或更可靠的基础模型；这份单次对照不足以证明只换提示词就能解决。\n\n## 限制与线上状态\n';
for(const l of audit.limitations)report+=`\n- ${l}\n`;
report+=`\n正式HEAD：${formal.production_commit}；核对的6个运行源码/模板SHA256均与测试前一致；默认模型和温度不变，三个服务在线，正式域名返回${formal.public_http_status}。线上另一工作区的唤醒音频改动保留，本次未处理或提交。未部署此候选。\n\n完整400轮原文及22道MCP记录：PROMPT_ONLY_FULL_TRANSCRIPTS_20261006.md。逐题判断和延迟分布：prompt-only-reviewed-results.json。原始上游记录：prompt-only-comparison.json、prompt-only-mcp-current.json、prompt-only-mcp-prompt_only.json。\n`;
fs.writeFileSync(path.resolve('docs/PROMPT_ONLY_COMPARISON_20261006.md'),report,'utf8');
const compact=data.dialogues.map(d=>({id:d.id,variant:d.variant,persona:d.persona,scenario:d.scenario,persona_prompt:d.persona_prompt,turns:d.turns.map(r=>({turn:r.turn,user:r.user,assistant:r.assistant,proposals:r.tool_proposals.length}))}));
const embedded=JSON.stringify({stats,mcp,recall,examples,titles,names,dialogues:compact});
const canvas=`import {useState,useHostTheme,Stack,Row,Grid,H1,H2,Text,Select,Table,Callout,Divider} from "cursor/canvas";
const DATA=${embedded};
export default function PromptOnlyComparison(){
 const theme=useHostTheme(); const [persona,setPersona]=useState('natural'); const [scene,setScene]=useState('0');
 const a=DATA.dialogues.find(d=>d.variant==='current'&&d.persona===persona&&d.scenario===Number(scene))!;
 const b=DATA.dialogues.find(d=>d.variant==='prompt_only'&&d.persona===persona&&d.scenario===Number(scene))!;
 return <Stack gap={20} style={{padding:24,color:theme.text.primary,background:theme.bg.editor}}>
 <H1>新提示词单独替换：尚未通过上线验收</H1>
 <Text tone="secondary">2026-10-06 · 默认 qwen3.8-flash · 温度0.4 · 100个输入 × 2个人格 × 2版 = 400轮实际回复</Text>
 <Callout>保留原有工具回执保护；没有逐句校验、重试或二次润色。事实子集有所改善，但仍编造进度、忽略反馈和正文假装调用；本次没有部署。</Callout>
 <H2>对照结果</H2>
 <Table headers={['指标','当前线上','新提示词']} rows={[
 ['回复处理完成（不等于质量通过）','200 / 200','200 / 200'],
 ['事实回忆子集：全文无明确事实冲突',DATA.stats.current.strict_recall_passed+'/18',DATA.stats.prompt_only.strict_recall_passed+'/18'],
 ['工具用例人工复核',DATA.mcp.current.passed+'/11',DATA.mcp.prompt_only.passed+'/11'],
 ['本轮真实时间查询',DATA.mcp.current.fresh_query_passed+'/6',DATA.mcp.prompt_only.fresh_query_passed+'/6'],
 ['首段文字进入TTS队列中位数（ms）',DATA.stats.current.first_tts_enqueue_p50_ms,DATA.stats.prompt_only.first_tts_enqueue_p50_ms],
 ['首段文字进入TTS队列P95（ms）',DATA.stats.current.first_tts_enqueue_p95_ms,DATA.stats.prompt_only.first_tts_enqueue_p95_ms],
 ['平均回复长度（字符）',DATA.stats.current.mean_reply_chars,DATA.stats.prompt_only.mean_reply_chars]]}/>
 <Text size="small" tone="secondary">来源：服务器真实生产处理器对照；延迟为文字入队，不是设备实际听到声音。单次实验，每版18道事实题，不代表整体自然程度成功率。未测试实体设备。</Text>
 <Divider/>
 <H2>完整逐轮对话对照</H2>
 <Row gap={12} wrap><Select value={persona} onChange={setPersona} options={[{value:'natural',label:'随和自然人格'},{value:'existing-playful',label:'原有调皮人格'}]}/><Select value={scene} onChange={setScene} options={DATA.titles.map((label,i)=>({value:String(i),label:(i+1)+'. '+label}))}/></Row>
 <Text tone="secondary">人格原文：{a.persona_prompt}</Text>
 <Table headers={['轮次 / 用户','当前线上提示词','新提示词']} rows={a.turns.map((r,i)=>[
 <Stack gap={6}><Text weight="semibold">第{r.turn}轮</Text><Text>{r.user}</Text></Stack>,
 <Stack gap={6}><Text style={{whiteSpace:'pre-wrap'}}>{r.assistant}</Text>{r.proposals>0&&<Text tone="secondary" size="small">提出工具调用{r.proposals}次，测试阶段未执行</Text>}</Stack>,
 <Stack gap={6}><Text style={{whiteSpace:'pre-wrap'}}>{b.turns[i].assistant}</Text>{b.turns[i].proposals>0&&<Text tone="secondary" size="small">提出工具调用{b.turns[i].proposals}次，测试阶段未执行</Text>}</Stack>])}/>
 <H2>工具用例：实际回答和真实调用次数</H2>
 <Table headers={['用户请求','当前回复 / 执行次数','新回复 / 执行次数']} rows={DATA.mcp.current.cases.map((r,i)=>[
 r.user,<Stack gap={6}><Text>{r.spoken}</Text><Text size="small" tone="secondary">实际调用{r.tool_events.length}次 · {r.reviewed_pass?'通过':'失败'}</Text></Stack>,
 <Stack gap={6}><Text>{DATA.mcp.prompt_only.cases[i].spoken}</Text><Text size="small" tone="secondary">实际调用{DATA.mcp.prompt_only.cases[i].tool_events.length}次 · {DATA.mcp.prompt_only.cases[i].reviewed_pass?'通过':'失败'}</Text></Stack>])}/>
 <Text tone="secondary" size="small">设备状态正文调用标签原自动断言漏判，本次人工记为失败；原始记录保留。固定聊天时间为10月3日零点，两版相同；MCP真实时间为10月6日。</Text>
 </Stack>;
}
`;
write('prompt-only-comparison.canvas.tsx',canvas);
console.log(JSON.stringify({stats,mcp:Object.fromEntries(variants.map(v=>[v,{passed:mcp[v].passed,total:mcp[v].total,real_tool_calls:mcp[v].real_tool_calls}])),recall_reviewed:recall.length,complete_dialogues:data.dialogues.length},null,2));
