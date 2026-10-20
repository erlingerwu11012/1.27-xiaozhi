const fs=require('fs'),assert=require('assert'),path=require('path');
const root=path.resolve('docs/natural-dialogue-presets-20261005');
const load=n=>JSON.parse(fs.readFileSync(path.join(root,n),'utf8'));
const result=load('persona-runtime-results-20261007.json'),inventory=load('persona-inventory-20261007.json'),billing=load('persona-billing-audit-20261007.json');
assert(result.finished&&result.customer_configuration_unchanged&&billing.passed);
const rows=result.sessions.flatMap(s=>s.turns.map(r=>({...r,key:`${s.persona_id}/${s.repeat}/${s.scenario}/${r.turn}`,persona_id:s.persona_id,persona_name:s.persona_name,repeat:s.repeat,scenario:s.scenario})));
assert.equal(rows.length,182);assert(rows.every(r=>r.runtime_ok&&!r.error&&r.assistant));
const issue=(key,category,severity,note)=>{const r=rows.find(r=>r.key===key);assert(r);return {key,category,severity,note,persona_id:r.persona_id,persona_name:r.persona_name,repeat:r.repeat,scenario:r.scenario,turn:r.turn,user:r.user,assistant:r.assistant};};
const issues=[
 issue('current/1/light/3','猜测用户心理','明确问题','用户只说鞋摆在门口，模型却说鞋在享受“你的愧疚感”。这不是用户提供的情绪。'),
 issue('current/1/help/1','幼龄化与指责','明确问题','给优先级建议时用了“乖乖去写报告吧，别想着偷懒”，把善意调侃放大为训话。'),
 issue('natural/2/light/2','虚构用户事实','明确问题','用户只说跑步鞋一天没穿，没有说待在家里或躺了一天。'),
 issue('partner/2/light/3','虚构用户事实','明确问题','允许打趣仍不能把“你在家躺了一天”当作已经发生的事实。'),
 issue('rational/1/light/2','闲聊变成建议','明确问题','同一场景用户已说不用安排，之后只是分享鞋没穿；模型仍建议把鞋收起来。'),
 issue('playful/2/serious/3','认真场景重新调侃','明确问题','前面已表达烦躁并要求只说事情；此处再次取笑进度。与该模板“认真时收住”的要求不符。'),
 issue('rational/1/light/4','日常交流偏术语','表达偏离','出现“信息环境”“认知背景”“低成本的知识激活方式”。与模板的日常不卖弄术语不够一致。'),
 issue('rational/2/light/4','过度概括','表达偏离','把书脊朝外说成只是装饰，把封面朝外说成才能触发阅读，措辞过于绝对。'),
 issue('listener/2/help/3','表达偏抽象','表达偏离','用户要求具体看法、不要人生道理，但回复转向“未来的自己”和“现在的自己”。'),
 issue('partner/2/help/3','闲聊比喻过多','表达偏离','用存钱花钱解释买书读书，偏离一个具体看法和理由的要求。'),
 issue('natural/1/light/2','补充未提供的计划','表达偏离','用“运动计划又泡汤了？”提问，额外假定有运动计划和重复失败；以问句表达，单列提醒而不计为确定事实断言。'),
 issue('partner/2/light/2','补充未提供的计划','表达偏离','断定运动计划彻底搁置，但用户只说鞋没穿。'),
];
const metrics=[];
const check=(label,subset,test,method)=>{const passed=subset.filter(test).length;metrics.push({label,passed,total:subset.length,method});assert.equal(passed,subset.length,label);};
check('实际输出成功',rows,r=>r.runtime_ok&&!!r.assistant,'程序检查：有正文，处理器成功，无接口异常。');
check('报告半完成状态核对',rows.filter(r=>r.scenario==='serious'&&r.turn===4),r=>/一半/.test(r.assistant)&&/不能|不等于/.test(r.assistant),'人工复核并检查原文：保留已完成一半，否定“从来没写过”。不代表所有事实均通过。');
check('明确要求别逗后的收住',rows.filter(r=>r.scenario==='light'&&r.turn===4),r=>!r.assistant.includes('慢慢来')&&!/[？?]/.test(r.assistant),'人工复核14条：没有继续取笑、反问或说“慢慢来”；部分仍偏长或抽象。');
check('不反问的明确反馈',rows.filter(r=>r.scenario==='help'&&r.turn===2),r=>!/[？?]/.test(r.assistant),'程序检查并人工阅读：请求不要反问之后未反问。');
check('应查时间的真实 MCP',rows.filter(r=>r.scenario==='tools'&&r.turn===1),r=>r.tool_events.length===1&&r.tool_events[0].arguments.timezone==='Europe/London'&&!r.tool_events[0].blocked_by_test_harness,'核对真实工具事件、地区参数与回执；14条由模型发起原生调用。');
check('明确禁止查询时不调用',rows.filter(r=>r.scenario==='tools'&&r.turn===2),r=>r.tool_events.length===0&&r.model_requests.every(m=>Object.keys(m.tool_calls).length===0),'核对工具事件和原生tool_calls均为空。');
check('未输出动作或情绪标签',rows,r=>! /\[(?:smirk|wink|grin|laugh|emotion|happy|sad|excited)[^\]]*\]|\*[^*]+\*/i.test(r.assistant),'程序扫描加人工阅读；只针对明显的动作、情绪标签，不用此项代替自然度评价。');
assert(rows.every(r=>r.model_requests.every(m=>m.reasoning_chars===0)));
const observations={
 current:'调侃最明显；偶发猜测情绪、训话和幼龄用词。人格生效，但表达边界不稳定。',
 natural:'日常比较自然；与倾听、搭档有重合，一次玩笑编出了用户躺在家里。',
 listener:'认真场景温和简短；通常能接住情绪，部分观点表达仍偏抽象。',
 humorous:'轻松场景有物品打趣；与俏皮调侃高度相近，认真场景大多能收住。',
 rational:'理由和分析更明显；有一次主动安排，部分日常话题科普化、术语化。',
 partner:'明确求建议时务实；闲聊多接近自然朋友，出现一次虚构用户当天活动。',
 playful:'玩笑通常比当前自定义人格温和；一次认真场景重新讽刺进度。',
};
const recommendations=[
 '保留人格选择和自定义权。当前数据证明人格文字进入了模型，问题主要是执行边界及风格区分。',
 '人格模板补充两到三条行为和简短对话示例；不要只依赖“温柔、理性、腹黑”等抽象标签，也不要要求每句体现性格。',
 '把幽默边界写成具体行为：可以调侃当前话题，不能补出用户当天活动、动机和情绪；不要用宝宝、乖乖等词建立上下级语气。',
 '六个模板分别明确侧重点：朋友分享看法、倾听接住具体感受、幽默打趣情境、理性用日常词说理由、搭档只在求助时梳理、俏皮在严肃反馈后收住。',
 '优化后复用这套输入再次测试。这次只读取和测试，没有修改生产人格、提示词或模型。',
];
const review={date_beijing:result.date_beijing,conclusion:'人格配置和注入正确，模型能够体现部分性格；尚未稳定达到预设的完整要求。',metrics,issues,observations,recommendations,review_method:'182条输出人工阅读；硬约束采用明确题目与程序核对。自然度、模板区分及表达偏离是定性审查，不用关键词命中率包装成人格成功率。',limits:result.scope,finished:true};
fs.writeFileSync(path.join(root,'persona-runtime-reviewed-20261007.json'),JSON.stringify(review,null,2));
const md=[];const line=s=>md.push(s);
line('# 当前人格与六个预设：实际模型测试');line('');line(review.conclusion);line('');
line(`测试时间：${new Date(result.date_beijing).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}（北京时间）。`);
line('');line('模型 qwen3.7-plus，非思考，温度0.4，输出上限600。七种人格使用相同13句输入，分成四个独立多轮场景，重复两轮，共182条回复。使用生产提示词组装、正式ConnectionHandler及文本输出处理，通过正式one-api和所属设备账户的签名计费。没有修改任何生产人格或模型设置。');
line('');line('真实硬件语音未测试；没有注入个人聊天历史或长期记忆。工具只执行真实时间查询，没有设备操作或用户业务写入。人格预设只在独立测试会话里替换，未写回账户。');
line('');line('## 当前生效的人格');line('');line('> '+inventory.current_persona);line('');line('当前文本为自定义人格，不匹配六个预设。七种人格的原文均完整注入；当前人格组装出的system SHA256与只读快照相同。');
line('');line('## 验证结果');line('');for(const m of metrics)line(`- ${m.label}：${m.passed}/${m.total}。${m.method}`);
line('');line('这些数字分别对应具体测试题，不能合并成“人格整体100%通过”。报告状态题通过，也不能掩盖其他话题中出现的虚构。');
line('');line('## 七种人格的表现');line('');for(const p of result.personas)line(`- ${p.name}：${observations[p.id]}`);
line('');line('## 问题原文及审查理由');for(const i of issues){line('');line(`### ${i.persona_name} · 第${i.repeat}轮 ${i.scenario}/${i.turn} · ${i.category}（${i.severity}）`);line('');line('用户：'+i.user);line('');line('模型：'+i.assistant);line('');line('审查：'+i.note);}
line('');line('## 建议');line('');for(const r of recommendations)line('- '+r);
line('');line('相同平台规则和同一个模型下，若干预设输出非常相近。当前结果不能单独证明平台提示词压住了人格：抽象模板、模型习惯及相同场景措辞都可能影响结果，需要进一步控制变量测试。');
line('');line('## 真实执行与账单核验');line('');line(`182个签名请求对应182笔已结算账单，没有重复请求ID。输入合计${billing.token_usage.input_tokens} token、输出${billing.token_usage.output_tokens} token、缓存输入${billing.token_usage.cached_tokens} token。上游成本${billing.upstream_cost_cny_display}元，按原规则折算的销售金额${billing.sale_currency_cny_display}元；实际积分扣减仍依充值批次换算，不能把该金额直接当作钱包中的现金扣款。`);
line('');line(`以上用量是182次请求累加，不是单个会话上下文。每次输入范围${billing.single_request_input_min}至${billing.single_request_input_max} token，独立场景最多四轮，没有接近18万token压缩阈值。`);
line('');line('## 全部原始对话');
for(const s of result.sessions){line('');line(`### ${s.persona_name} · 第${s.repeat}轮 · ${result.scenarios.find(x=>x.id===s.scenario).name}`);line('');line('人格：'+result.personas.find(p=>p.id===s.persona_id).prompt);for(const r of s.turns){line('');line('用户：'+r.user);line('');line('回复：'+r.assistant);const raw=r.model_requests.map(m=>m.raw_text).filter(Boolean).join('\n');if(raw&&raw!==r.assistant){line('');line('模型原始正文（与处理后输出不同）：'+raw);}if(r.tool_events.length){line('');line('真实工具：'+r.tool_events.map(e=>e.name+' '+JSON.stringify(e.arguments)).join('；'));line('');line('回执：'+r.tool_events.map(e=>e.receipt).join('\n'));}}}
fs.writeFileSync(path.join(root,'PERSONA_RUNTIME_REPORT_20261007.md'),md.join('\n')+'\n');
const data={personas:result.personas,scenarios:result.scenarios,metrics,issues,observations,recommendations,date:result.date_beijing,model:result.model,temperature:result.temperature,turns:rows.map(r=>({key:r.key,persona_id:r.persona_id,persona_name:r.persona_name,repeat:r.repeat,scenario:r.scenario,turn:r.turn,user:r.user,assistant:r.assistant,raw:r.model_requests.map(m=>m.raw_text).filter(Boolean).join('\n'),native_calls:r.model_requests.flatMap(m=>Object.values(m.tool_calls)),tool_events:r.tool_events,elapsed_ms:r.elapsed_ms})),billing,scope:result.scope};
const code=`import {useState,useHostTheme,H1,H2,H3,Text,Row,Grid,Select,Table,Callout,Divider} from "cursor/canvas";
const data=${JSON.stringify(data)};
export default function PersonaReport(){
 const theme=useHostTheme();
 const [persona,setPersona]=useState("current"),[scene,setScene]=useState("light"),[repeat,setRepeat]=useState("1"),[turn,setTurn]=useState("2");
 const selected=data.personas.find(p=>p.id===persona)!;
 const selectedScene=data.scenarios.find(s=>s.id===scene)!;
 const entries=data.turns.filter(r=>r.persona_id===persona&&r.scenario===scene&&r.repeat===Number(repeat));
 const comparison=data.turns.filter(r=>r.scenario===scene&&r.turn===Number(turn)&&r.repeat===Number(repeat));
 const problems=data.issues.filter(i=>i.persona_id===persona);
 const surface={background:theme.fill.tertiary,padding:14,whiteSpace:"pre-wrap" as const,overflowWrap:"anywhere" as const,lineHeight:1.7};
 return <main style={{maxWidth:1180,padding:24,color:theme.text.primary}}>
  <H1>人格已生效，表达边界仍需完善</H1>
  <Text style={{color:theme.text.secondary}}>2026-10-07 · Qwen3.7 Plus · 非思考 · 温度0.4 · 正式 one-api · 当前人格及六种预设 · 两轮相同输入</Text>
  <p>182条原始回复全部保留。明确反馈和报告状态核对表现稳定；仍出现虚构当天活动、推测情绪、训话及模板差异不足。这些是分项测试，不能包装为整体人格成功率。</p>
  <Table headers={["明确测试项","通过/测试条数","统计口径"]} rows={data.metrics.map(m=>[m.label,m.passed+"/"+m.total,m.method])}/>
  <Divider/>
  <H2>相同输入，七种人格怎么回答</H2>
  <Row wrap gap={12}>
   <Select value={scene} onChange={v=>{setScene(v);setTurn("1");}} options={data.scenarios.map(s=>({value:s.id,label:s.name}))}/>
   <Select value={repeat} onChange={setRepeat} options={[{value:"1",label:"第1轮"},{value:"2",label:"第2轮"}]}/>
   <Select value={turn} onChange={setTurn} options={selectedScene.turns.map((u,i)=>({value:String(i+1),label:"第"+(i+1)+"句："+u.slice(0,25)}))}/>
  </Row>
  <p style={surface}>{selectedScene.turns[Number(turn)-1]}</p>
  <Table headers={["人格","实际完整回复"]} rows={comparison.map(r=>[r.persona_name,r.assistant])}/>
  <Divider/>
  <H2>查看完整多轮对话</H2>
  <Select value={persona} onChange={setPersona} options={data.personas.map(p=>({value:p.id,label:p.name}))}/>
  <p style={surface}>{selected.prompt}</p>
  <p>{data.observations[persona as keyof typeof data.observations]}</p>
  <Grid columns="minmax(0, 2fr) minmax(0, 1fr)" gap={24} align="start">
   <section>{entries.map(r=><section key={r.key} style={{marginBottom:22}}>
    <H3>第{r.turn}句</H3><p style={{color:theme.text.secondary}}>用户：{r.user}</p><p style={surface}>{r.assistant}</p>
    {r.raw&&r.raw!==r.assistant&&<details><summary>主模型原始正文</summary><p style={surface}>{r.raw}</p></details>}
    {r.native_calls.length>0&&<details><summary>模型原生工具调用</summary><pre style={surface}>{JSON.stringify(r.native_calls,null,2)}</pre></details>}
    {r.tool_events.length>0&&<details><summary>真实执行与回执</summary><pre style={surface}>{JSON.stringify(r.tool_events,null,2)}</pre></details>}
    <Text style={{color:theme.text.tertiary}}>处理耗时 {r.elapsed_ms} 毫秒</Text>
   </section>)}</section>
   <aside>
    <H3>对该人格的审查</H3>
    {problems.length>0?problems.map(i=><section key={i.key+"/"+i.category} style={{marginBottom:18}}><p><strong>{i.category}</strong> · {i.severity}</p><p>{i.note}</p><Text style={{color:theme.text.secondary}}>第{i.repeat}轮 · {i.scenario}/{i.turn}</Text></section>):<p>{data.observations[persona as keyof typeof data.observations]}</p>}
   </aside>
  </Grid>
  <Divider/><H2>改进方向</H2>{data.recommendations.map((r,i)=><p key={i}>{i+1}. {r}</p>)}
  <Callout>未修改任何生产人格、提示词或模型设置。{data.scope}。模板区分是定性判断，不能仅凭这次结果判定是模型能力或提示词长度的单一原因。</Callout>
  <details style={{marginTop:16}}><summary>实际执行及计费证据</summary><p>182个签名请求，182笔已结算账单，原计费规则保留；上游成本 {data.billing.upstream_cost_cny_display} 元，销售金额折算 {data.billing.sale_currency_cny_display} 元。实际积分扣减按充值批次换算。</p></details>
 </main>;
}
`;
const canvas='C:/Users/Administrator/.cursor/projects/e-github-github-code-all-4-30/canvases/persona-runtime-review.canvas.tsx';
fs.writeFileSync(canvas,code);
// Check syntax and component props against the actual Canvas SDK declarations.
const validation=path.join(__dirname,'report-validation/node_modules');
const sdk='C:/Users/Administrator/.cursor/skills-cursor/canvas/sdk/index.d.ts';
const configPath=path.join(__dirname,'report-validation/tsconfig.json');
fs.writeFileSync(configPath,JSON.stringify({files:[canvas],compilerOptions:{noEmit:true,strict:true,skipLibCheck:true,target:'ES2022',module:'ESNext',moduleResolution:'Bundler',jsx:'react-jsx',types:[],paths:{'cursor/canvas':[sdk],'react':[path.join(validation,'@types/react/index.d.ts')],'react/jsx-runtime':[path.join(validation,'@types/react/jsx-runtime.d.ts')]}}},null,2));
const checked=require('child_process').spawnSync(process.execPath,[path.join(validation,'typescript/bin/tsc'),'--project',configPath],{encoding:'utf8'});
if(checked.status!==0){console.error(checked.stdout+checked.stderr);process.exit(1);}
const sdkExports=fs.readFileSync('C:/Users/Administrator/.cursor/skills-cursor/canvas/sdk/index.d.ts','utf8');
for(const name of ['useState','useHostTheme','H1','H2','H3','Text','Row','Grid','Select','Table','Callout','Divider'])assert(sdkExports.includes(name));
console.log(JSON.stringify({turns:rows.length,issues:issues.length,metrics,canvas,typescript:'no_errors',sdk_exports:'verified',visual_render:'not_yet_verified'},null,2));
