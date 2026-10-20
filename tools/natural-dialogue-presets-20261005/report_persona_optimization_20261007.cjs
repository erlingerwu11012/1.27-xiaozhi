const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve('docs/natural-dialogue-presets-20261005');
const read=n=>JSON.parse(fs.readFileSync(path.join(root,n),'utf8'));
const before=read('persona-runtime-results-20261007.json'),after=read('persona-refined-runtime-results-20261007.json'),heldout=read('persona-refined-heldout-results-20261007.json');
const candidate=read('persona-optimization-candidate-20261007.json'),billing=read('persona-optimization-billing-20261007.json'),probe=read('persona-injection-probe-results-20261007.json');
const flatten=d=>d.sessions.flatMap(s=>s.turns.map(r=>({...r,key:`${s.persona_id}/${s.repeat}/${s.scenario}/${r.turn}`,persona_id:s.persona_id,persona_name:s.persona_name,repeat:s.repeat,scenario:s.scenario})));
const old=flatten(before),now=flatten(after),extra=flatten(heldout);
assert(before.finished&&after.finished&&heldout.finished&&billing.passed&&probe.finished);
assert.equal(now.length,182);assert.equal(extra.length,35);
assert.deepEqual(after.scenarios,before.scenarios);
assert.equal(after.tool_catalog_sha256,before.tool_catalog_sha256);
assert.equal(after.personas[0].prompt,before.personas[0].prompt);
assert.equal(after.persona_execution_guidance,candidate.execution_guidance);
assert.equal(after.candidate_prompt_manager_sha256,heldout.candidate_prompt_manager_sha256);
assert.equal(after.candidate_prompt_manager_sha256,probe.candidate_prompt_manager_sha256);
assert(after.customer_configuration_unchanged&&heldout.customer_configuration_unchanged);
assert(flatten(probe).every(r=>r.model_requests.every(m=>m.persona_in_actual_request)));
for(const r of now)assert.equal(r.user,old.find(o=>o.key===r.key).user);
const metrics=[];
function metric(label,rows,pred,scope){metrics.push({label,passed:rows.filter(pred).length,total:rows.length,scope});}
metric('实际文本输出',now.concat(extra),r=>r.runtime_ok&&r.assistant&&!r.error,'完整182条同题与35条新题；未做实机语音验收。');
metric('原题最终核对报告状态',now.filter(r=>r.scenario==='serious'&&r.turn===4),r=>/一半/.test(r.assistant)&&/不能|不等于|不代表/.test(r.assistant),'人工复核14条最终核对题；之前一条中间回复把一半说成一大半，仍列为失败。');
metric('新题核对更新后的拼图状态',extra.filter(r=>r.turn===4),r=>/三分之一/.test(r.assistant)&&/不能/.test(r.assistant),'七种人格各一次；不代表所有状态更新均可靠。');
metric('真实 MCP 时间查询',now.filter(r=>r.scenario==='tools'&&r.turn===1),r=>r.tool_events.length===1&&r.tool_events[0].arguments.timezone==='Europe/London'&&!r.tool_events[0].blocked_by_test_harness&&r.model_requests.some(m=>Object.keys(m.tool_calls).length),'核对原生调用和真实回执；本轮只测时间查询，未重测全部设备工具。');
metric('禁止查时间时不调用',now.filter(r=>r.scenario==='tools'&&r.turn===2),r=>r.tool_events.length===0&&r.model_requests.every(m=>Object.keys(m.tool_calls).length===0),'概念解释题，不执行查询。');
metric('明确要求不反问后无问句',now.filter(r=>r.scenario==='help'&&r.turn===2),r=>!/[?？]/.test(r.assistant),'只检验不反问；内容抽象仍独立列为问题。');
const knownKeys=['current/1/light/3','current/1/help/1','natural/2/light/2','partner/2/light/3','rational/1/light/2','playful/2/serious/3'];
const notes=['对应回复不再猜测用户愧疚，改为调侃鞋。','对应回复不再用“乖乖、别偷懒”训话；其他轮次仍出现对拖延倾向的推定。','对应回复未再虚构用户在家躺了一天。','对应回复未再虚构用户在家躺了一天。','对应回复不再建议把鞋收起来。','对应回复不再评价进度慢，保留半完成状态；其他轮次的认真场景仍有打趣。'];
const paired=knownKeys.map((key,i)=>{const a=old.find(r=>r.key===key),b=now.find(r=>r.key===key);return {key,persona_name:b.persona_name,user:b.user,before:a.assistant,after:b.assistant,note:notes[i]};});
const issue=(key,title,note)=>{const r=now.concat(extra).find(r=>r.key===key);assert(r);return {key,title,note,persona_name:r.persona_name,user:r.user,assistant:r.assistant};};
const issues=[
 issue('current/1/serious/3','认真场景重新开玩笑','先前已表达烦躁并要求只谈事情，仍用“合着……为了衬托标题”讽刺进度。'),
 issue('current/2/help/1','推定用户会拖延','“最容易被你无限期拖延”是对用户倾向的额外推断；没有必要给建议附加这个判断。'),
 issue('playful/1/light/3','玩笑转成对用户的评价','“比你有毅力”把笑点从鞋转向比较用户毅力，不符合候选规定的边界。'),
 issue('humorous/2/serious/3','中途事实反转','用户明确写好一半，回复却说剩一大半；下一句答对不抹去这条错误。'),
 issue('humorous/1/help/3','要求具体后仍用抽象解释','仍出现“占有欲、认知劳动”，并给出很多人只买不读的概括；没有充分执行新的日常表达要求。'),
 issue('natural/1/heldout/5','机械套用提示词示例','把锅的展示示例套成“这口拼图”，词语搭配生硬；增加示例也有照搬的副作用。'),
 issue('playful/1/heldout/5','猜测未提供的用户意图','“知道你要休息”并非用户说过的事实，允许玩笑不等于允许补出休息意图。'),
];
const comparison=now.map(r=>({...r,before:old.find(o=>o.key===r.key).assistant}));
const report={conclusion:'已形成可审阅的人格提示词候选，部分旧问题在对应回复中改善；仍未达到稳定执行全部人格边界的程度，不建议直接替换线上。',metrics,paired,issues,scope:after.scope,review_method:'逐条阅读最终182条原题及35条新题；同一题、相同参数、同一工具目录。旧结果为此前基线，不是并发随机对照。两轮样本不足以证明总体错误率下降。',unchanged_custom_persona:after.personas[0].prompt,original_persona_preserved:true,production_changed:false,model:after.model,temperature:after.temperature};
fs.writeFileSync(path.join(root,'persona-optimization-reviewed-20261007.json'),JSON.stringify(report,null,2));
const promptMd=['# 人格提示词优化候选','',report.conclusion,'','保留当前自定义人格原文：','',`> ${report.unchanged_custom_persona}`,'','## 人格共同执行边界','',candidate.execution_guidance,'','## 六个人格预设',''];
for(const p of candidate.presets)promptMd.push(`### ${p.name}`,'',p.description,'',p.prompt,'');
promptMd.push('## 这版改了什么','',
 '- 性格词后增加具体说话行为，明确各预设侧重点。',
 '- 每个预设加两句简短示例，原题没有直接写入提示词；实测仍有机械套用示例的风险。',
 '- 共同边界区分调侃情境与评价用户，认真和不要建议的反馈持续生效。',
 '- 不要求每句展示人格；日常倾向一至三句，具体看法用日常词说理由。',
 '- 自定义原文、工具定义、检索、执行保护、模型、计费和生产代码均保持原样；修改只在隔离进程生效。','',
 '这版属于候选，不是保证模型完全服从人格的机制。用户仍然可以选择和自定义性格，但实际表达需要继续按对话场景评估。','');
fs.writeFileSync(path.join(root,'PERSONA_OPTIMIZED_PROMPTS_20261007.md'),promptMd.join('\n'));
const md=['# 人格优化：相同原题与新题复测','',report.conclusion,'',report.review_method,'',`Qwen3.7 Plus；非思考；温度0.4；max_tokens600；正式one-api及设备所属账户签名计费。最终版182条原题、35条新题；另7条核对实际模型请求中包含新规则及各人格原文。`,
 '',report.scope+'。未改生产配置，没有硬件或用户数据写入。','',
 '## 分项结果',''];
for(const m of metrics)md.push(`- ${m.label}：${m.passed}/${m.total}。${m.scope}`);
md.push('','这些分项数字不能作为“人格整体成功率”。玩笑边界、自然度、风格区分仍有明显不足。','',
 '## 六处旧问题的对应原文对照','',
 '这些条目按上一次已经发现的问题选取，用于定位改动效果；不是随机样本，不能据此计算总体错误率。');
for(const p of paired)md.push('',`### ${p.persona_name} · ${p.key}`,'','用户：'+p.user,'','旧版：'+p.before,'','新版：'+p.after,'','审查：'+p.note);
md.push('','## 最终候选仍存在的问题');
for(const i of issues)md.push('',`### ${i.persona_name} · ${i.key} · ${i.title}`,'','用户：'+i.user,'','模型：'+i.assistant,'','审查：'+i.note);
md.push('','## 人格与工具是否真正参与请求','',
 '七种人格的额外核验请求全部确认：实际送入模型的system包含候选执行边界和对应原文。最终候选182题沿用同一生产请求路径。新旧工具目录SHA256一致，模型、温度、非思考配置均由测试脚本断言。',
 '', '共同执行边界只替换PromptManager的layer2局部，程序断言该局部之前、之后的源码完全一致；线上文件未写入。',
 '', '六种人格的措辞仍较接近，例句并未保证更稳定的区别。当前用户人格的“腹黑、捉弄”会增加调侃强度；不改用户原文，仅补边界仍不能完全控制。','',
 '## 请求量与计费核验','');
for(const a of billing.audits)md.push(`- ${a.file}：${a.signed_requests}个签名请求，${a.settled_bills}笔已结算；上游成本${a.upstream_cost_cny}元，销售折算${a.sale_currency_cny}元；单请求输入${a.input_min}–${a.input_max} token。`);
md.push('','以上销售折算不等于现金钱包扣款，实际积分扣减沿用充值批次规则。包括不采用的第一版全部请求；无额外润色模型或思考请求。','',
 '## 最终候选完整原始对话','');
for(const dataset of [after,heldout])for(const s of dataset.sessions){md.push('',`### ${s.persona_name} · 第${s.repeat}轮 · ${s.scenario}`,'','人格：'+dataset.personas.find(p=>p.id===s.persona_id).prompt);for(const r of s.turns){md.push('','用户：'+r.user,'','回复：'+r.assistant);const raw=r.model_requests.map(m=>m.raw_text).filter(Boolean).join('\n');if(raw!==r.assistant)md.push('','模型原始正文：'+raw);if(r.tool_events.length)md.push('','原生工具调用及真实执行：'+JSON.stringify(r.tool_events,null,2));}}
fs.writeFileSync(path.join(root,'PERSONA_OPTIMIZATION_REPORT_20261007.md'),md.join('\n')+'\n');
const data={...report,personas:after.personas,scenarios:after.scenarios,comparison,heldout:extra,candidate};
const code=`import {useState,useHostTheme,H1,H2,H3,Text,Row,Select,Table,Callout,Divider} from "cursor/canvas";
const data=${JSON.stringify(data)};
export default function PersonaOptimization(){
 const theme=useHostTheme();
 const [persona,setPersona]=useState("current"),[scene,setScene]=useState("serious"),[repeat,setRepeat]=useState("1");
 const rows=data.comparison.filter(r=>r.persona_id===persona&&r.scenario===scene&&r.repeat===Number(repeat));
 const fresh=data.heldout.filter(r=>r.persona_id===persona);
 const p=data.personas.find(p=>p.id===persona)!;
 const surface={background:theme.fill.tertiary,padding:14,lineHeight:1.7,whiteSpace:"pre-wrap" as const,overflowWrap:"anywhere" as const};
 return <main style={{maxWidth:1160,padding:24,color:theme.text.primary}}>
  <H1>人格优化候选：有改善，仍有边界失守</H1>
  <Text style={{color:theme.text.secondary}}>同题182条 · 新题35条 · Qwen3.7 Plus · 非思考 · 温度0.4 · 生产配置未变</Text>
  <p>{data.conclusion}</p>
  <Table headers={["测试项","通过/总数","范围"]} rows={data.metrics.map(m=>[m.label,m.passed+"/"+m.total,m.scope])}/>
  <Callout>分项通过率不代表人格整体成功率。中间回复仍有“一半”变“一大半”；即使最终核对答对，也保留为失败。</Callout>
  <Divider/><H2>完整多轮对话：旧版与候选并排</H2>
  <Row gap={12} wrap>
   <Select value={persona} onChange={setPersona} options={data.personas.map(p=>({value:p.id,label:p.name}))}/>
   <Select value={scene} onChange={setScene} options={data.scenarios.map(s=>({value:s.id,label:s.name}))}/>
   <Select value={repeat} onChange={setRepeat} options={[{value:"1",label:"第1轮"},{value:"2",label:"第2轮"}]}/>
  </Row>
  <details><summary>此人格的候选原文</summary><p style={surface}>{p.prompt}</p></details>
  {rows.map(r=><section key={r.key} style={{marginTop:18}}><H3>第{r.turn}句</H3><p style={surface}>用户：{r.user}</p><Table headers={["旧版实际回复","候选实际回复"]} rows={[[r.before,r.assistant]]}/>{r.tool_events.length>0&&<details><summary>真实工具调用及回执</summary><pre style={surface}>{JSON.stringify(r.tool_events,null,2)}</pre></details>}</section>)}
  <Divider/><H2>此人格的新题完整对话</H2>
  {fresh.map(r=><section key={r.key} style={{marginTop:16}}><p style={{color:theme.text.secondary}}>用户：{r.user}</p><p style={surface}>{r.assistant}</p></section>)}
  <Divider/><H2>候选仍未解决的问题</H2>
  {data.issues.map(i=><section key={i.key} style={{marginTop:18}}><H3>{i.persona_name} · {i.title}</H3><p>用户：{i.user}</p><p style={surface}>{i.assistant}</p><p>{i.note}</p></section>)}
  <Divider/><H2>共同执行边界及六种预设</H2><p style={surface}>{data.candidate.execution_guidance}</p>
  {data.candidate.presets.map(p=><details key={p.id} style={{marginTop:16}}><summary>{p.name} · {p.description}</summary><p style={surface}>{p.prompt}</p></details>)}
  <p style={{color:theme.text.secondary}}>{data.review_method}</p>
  <Callout>没有替换线上提示词或用户人格，也没有改工具、模型及计费。{data.scope}。</Callout>
 </main>;
}
`;
const canvas='C:/Users/Administrator/.cursor/projects/e-github-github-code-all-4-30/canvases/persona-optimization-review.canvas.tsx';
fs.writeFileSync(canvas,code);
const validation=path.join(__dirname,'report-validation/node_modules'),configPath=path.join(__dirname,'report-validation/tsconfig-persona-optimization.json');
fs.writeFileSync(configPath,JSON.stringify({files:[canvas],compilerOptions:{noEmit:true,strict:true,skipLibCheck:true,target:'ES2022',module:'ESNext',moduleResolution:'Bundler',jsx:'react-jsx',types:[],paths:{'cursor/canvas':['C:/Users/Administrator/.cursor/skills-cursor/canvas/sdk/index.d.ts'],'react':[path.join(validation,'@types/react/index.d.ts')],'react/jsx-runtime':[path.join(validation,'@types/react/jsx-runtime.d.ts')]}}},null,2));
const checked=require('child_process').spawnSync(process.execPath,[path.join(validation,'typescript/bin/tsc'),'--project',configPath],{encoding:'utf8'});
if(checked.status!==0){console.error(checked.stdout+checked.stderr);process.exit(1);}
console.log(JSON.stringify({metrics,known_problem_comparisons:paired.length,remaining_examples:issues.length,canvas,typescript:'no_errors',production_changed:false,raw_turns:now.length+extra.length},null,2));
