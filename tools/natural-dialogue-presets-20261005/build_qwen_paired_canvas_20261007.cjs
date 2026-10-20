const fs=require('fs'),assert=require('assert');
const base='docs/natural-dialogue-presets-20261005/';
const review=JSON.parse(fs.readFileSync(base+'qwen-paired-reviewed-20261007.json','utf8'));
const pack=JSON.parse(fs.readFileSync(base+'qwen-paired-tool-pack-20261006.json','utf8'));
const compact=r=>({model:r.model,id:r.id,trial:r.trial,reviewed_pass:r.reviewed_pass,steps:r.steps.map(s=>({text:s.text,calls:s.calls})),events:r.events,review_notes:r.review_notes,reviewed_continuation:r.reviewed_continuation});
const pairs=review.pairs.map(p=>{
 const plus=review.cases.find(r=>r.model==='qwen3.7-plus'&&r.id===p.id&&r.trial===p.trial);
 const flash=review.cases.find(r=>r.model==='qwen3.8-flash'&&r.id===p.id&&r.trial===p.trial);
 return {id:p.id,trial:p.trial,group:plus.group,user:plus.user,history:plus.history,expected:plus.expected,plus:compact(plus),flash:compact(flash)};
});
const data={summary:review.summary.map(s=>({model:s.model,passed:s.passed,total:s.total,positive:s.positive,negative:s.negative,rounds:s.rounds,groups:s.groups})),pairs,live:review.live.map(d=>({model:d.model,reviewed_pass:d.reviewed_pass,cases:d.cases.map(r=>({user:r.user,spoken:r.spoken,tool_events:r.tool_events,reviewed_success:r.reviewed_success,review_notes:r.review_notes}))})),guard:{tests:review.guard.tests},pack_sha256:review.pack_sha256,system:pack.cases[0].initial_messages[0].content};
const source=`import {useState,useHostTheme,H1,H2,Divider,Table} from "cursor/canvas";
type Count={passed:number;total:number};
type Summary=Count&{model:string;positive:Count;negative:Count;rounds:(Count&{trial:number})[];groups:(Count&{group:string})[]};
type ModelCase={model:string;id:number;trial:number;reviewed_pass:boolean;steps:{text:string;calls:unknown[]}[];events:unknown[];review_notes:string[];reviewed_continuation?:unknown};
type Pair={id:number;trial:number;group:string;user:string;history:unknown[];expected:unknown;plus:ModelCase;flash:ModelCase};
type LiveCase={user:string;spoken:string;tool_events:unknown[];reviewed_success:boolean;review_notes:string[]};
type Data={summary:Summary[];pairs:Pair[];live:{model:string;reviewed_pass:number;cases:LiveCase[]}[];guard:{tests:number};pack_sha256:string;system:string};
const DATA:Data=${JSON.stringify(data)};
const names:Record<string,string>={live_time:"时间查询（固定回执）",live_random:"随机工具（固定回执）",server_fixture:"提醒与习惯",clarify:"缺参数应询问",device_fixture:"设备操作",dependency:"先查状态再操作",multi_action:"多项操作",failure_receipt:"失败与空回执",missing_capability:"缺少对应能力",no_operation:"否定、引用与假设",device_no_operation:"设备讨论应不调用"};
const ratio=(v:Count)=>v.passed+"/"+v.total+"（"+(100*v.passed/v.total).toFixed(2)+"%）";
function ModelOutput({row}:{row:ModelCase}){
 const theme=useHostTheme();
 const code={whiteSpace:"pre-wrap" as const,overflowWrap:"anywhere" as const,background:theme.fill.tertiary,padding:12,fontSize:12,lineHeight:1.6};
 return <section>
  <H2>{row.model}</H2>
  <p style={{color:theme.text.secondary}}>{row.reviewed_pass?"调用决策通过":"调用决策失败"}</p>
  {row.review_notes.length>0&&<p>{row.review_notes.join("；")}</p>}
  {row.steps.map((step,index)=><div key={index} style={{marginBottom:16}}>
   <p>第 {index+1} 步 · 模型原文</p>
   <pre style={code}>{step.text||"该步没有正文"}</pre>
   <details><summary>原生 tool_calls</summary><pre style={code}>{JSON.stringify(step.calls,null,2)}</pre></details>
  </div>)}
  {row.events.length>0&&<details><summary>固定隔离回执与原保护层回复</summary><pre style={code}>{JSON.stringify(row.events,null,2)}</pre></details>}
  {row.reviewed_continuation!==undefined&&<details><summary>同义表达复核后接续原调用的补充记录</summary><pre style={code}>{JSON.stringify(row.reviewed_continuation,null,2)}</pre></details>}
 </section>;
}
export default function PairedQwenTools(){
 const theme=useHostTheme();const [trial,setTrial]=useState("1");const [mode,setMode]=useState("either");const [selected,setSelected]=useState(16);
 const current=DATA.pairs.filter(p=>(trial==="all"||String(p.trial)===trial)&&(mode==="all"||mode==="plus"&&!p.plus.reviewed_pass||mode==="flash"&&!p.flash.reviewed_pass||mode==="either"&&(!p.plus.reviewed_pass||!p.flash.reviewed_pass)));
 const pair=current.find(p=>p.id===selected)||current[0];
 const control={background:theme.bg.editor,color:theme.text.primary,border:"1px solid "+theme.stroke.primary,padding:8};
 return <main style={{background:theme.bg.editor,color:theme.text.primary,padding:24,maxWidth:1160,margin:"auto",fontSize:14,lineHeight:1.65}}>
  <H1>同一套提示词：Qwen 工具调用对照</H1>
  <p style={{color:theme.accent.primary}}>按可靠性优先的规则，选择 qwen3.7-plus。两者结果不同，未进入价格比较。</p>
  <p>140 条输入各测三轮，每模型 420 次。仅模型字段不同，420 对首轮请求哈希完全相同；非思考、温度 0.4。报告：2026-10-07。</p>
  <Table headers={["复核指标","qwen3.7-plus","qwen3.8-flash"]} rows={[
   ["全部调用决策",ratio(DATA.summary[0]),ratio(DATA.summary[1])],
   ["需要工具的操作请求",ratio(DATA.summary[0].positive),ratio(DATA.summary[1].positive)],
   ["不应调用的场景",ratio(DATA.summary[0].negative),ratio(DATA.summary[1].negative)],
   ...[1,2,3].map(n=>["第 "+n+" 轮决策",ratio(DATA.summary[0].rounds[n-1]),ratio(DATA.summary[1].rounds[n-1])]),
   ["真实 MCP 处理器验收",DATA.live[0].reviewed_pass+"/11",DATA.live[1].reviewed_pass+"/11"]
  ]} />
  <p style={{color:theme.text.secondary}}>定向案例通过率，包含否定、缺参数和缺能力场景；不能当作线上总体概率。设备、提醒用固定隔离回执，未做实机操作。真实 MCP 验收包含程序固定分支。</p>
  <H2>按功能查看调用决策</H2>
  <Table headers={["场景","qwen3.7-plus","qwen3.8-flash"]} rows={DATA.summary[0].groups.map(g=>[names[g.group]||g.group,ratio(g),ratio(DATA.summary[1].groups.find(r=>r.group===g.group)!)] )} />
  <Divider />
  <H2>原始对话与工具调用并排比较</H2>
  <div style={{display:"flex",gap:12,flexWrap:"wrap",alignItems:"center"}}>
   <label>轮次 <select style={control} value={trial} onChange={e=>setTrial(e.target.value)}><option value="1">第 1 轮</option><option value="2">第 2 轮</option><option value="3">第 3 轮</option><option value="all">三轮</option></select></label>
   <label>范围 <select style={control} value={mode} onChange={e=>setMode(e.target.value)}><option value="either">任一模型失败</option><option value="plus">Plus 失败</option><option value="flash">Flash 失败</option><option value="all">全部对话</option></select></label>
   {pair&&<label>用例 <select style={{...control,maxWidth:480}} value={pair.trial+":"+pair.id} onChange={e=>{const [n,id]=e.target.value.split(":");setTrial(n);setSelected(Number(id));}}>{current.map(p=><option key={p.trial+":"+p.id} value={p.trial+":"+p.id}>{p.trial}轮 #{p.id} · {p.user}</option>)}</select></label>}
  </div>
  {pair&&<>
   <p><strong>用户：</strong>{pair.user}</p>
   <p style={{color:theme.text.secondary}}>第 {pair.trial} 轮 · 用例 {pair.id} · {names[pair.group]||pair.group}</p>
   {pair.history.length>0&&<details><summary>双方完全相同的历史原文</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(pair.history,null,2)}</pre></details>}
   <details><summary>冻结的预期调用</summary><pre style={{whiteSpace:"pre-wrap"}}>{JSON.stringify(pair.expected,null,2)}</pre></details>
   <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(320px,1fr))",gap:28,marginTop:20}}><ModelOutput row={pair.plus}/><ModelOutput row={pair.flash}/></div>
  </>}
  <Divider />
  <H2>真实 MCP 原文</H2>
  {DATA.live.map(d=><details key={d.model} style={{marginBottom:12}}><summary>{d.model} · 复核 {d.reviewed_pass}/11</summary>{d.cases.map((r,i)=><div key={i} style={{margin:"12px 0"}}><p><strong>{r.user}</strong> · {r.reviewed_success?"通过":"失败"}</p><p style={{whiteSpace:"pre-wrap"}}>{r.spoken}</p>{r.review_notes.length>0&&<p>{r.review_notes.join("；")}</p>}<details><summary>实际 MCP 事件</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(r.tool_events,null,2)}</pre></details></div>)}</details>)}
  <H2>复核与执行保护</H2>
  <p>Flash 自动 290/420，复核 292/420：两条提醒内容同义表达纠正，保留初次调用并给双方补完后续；没有重抽首轮。真实 MCP 自动 10/11，复核 9/11：双城市请求只查一城，也要算失败。</p>
  <p>两模型都曾在空回执时误报成功，必须保留工具回执保护。保护候选回归 {DATA.guard.tests}/{DATA.guard.tests}。Plus 也有缺认人能力却拍照、使用目录外工具、失败后重复写入等边界错误，不承诺百分之百。</p>
  <p style={{color:theme.text.secondary}}>正式默认模型尚未切换，用户人格未改，没有部署；实机未验收。后续由模型生成的调用和历史自然不同，首轮输入完全一致，相同参数由同一固定回执规则处理。</p>
  <details><summary>本次实际冻结提示词（现有人格）</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{DATA.system}</pre></details>
  <p style={{color:theme.text.secondary,fontSize:12,overflowWrap:"anywhere"}}>输入包 SHA256：{DATA.pack_sha256}</p>
 </main>;
}
`;
const destination=base+'qwen-paired-tools.canvas.tsx';
fs.writeFileSync(destination,source);
const babel=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/lib/transform/babelBundle.js');
const parsed=babel.babelParse(source,destination,true);
assert(parsed.program.body.some(s=>s.type==='ExportDefaultDeclaration'));
assert(parsed.program.body.filter(s=>s.type==='ImportDeclaration').every(s=>s.source.value==='cursor/canvas'));
assert(!/fetch\(|boxShadow|linear-gradient|#[a-f0-9]{6}\b/.test(source));
assert.equal(data.pairs.length,420);
console.log(JSON.stringify({file:destination,pairs:data.pairs.length,syntax:'TSX parsed successfully',sdk_imports:'verified',bytes:Buffer.byteLength(source)}));
