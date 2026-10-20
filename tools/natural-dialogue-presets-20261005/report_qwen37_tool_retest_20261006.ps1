param([string]$CanvasPath)
$ErrorActionPreference='Stop'
$outDir=Join-Path $PSScriptRoot '../../docs/natural-dialogue-presets-20261005'
$variants=@('current','optimized','final','holdout')
$reviews=@()
function Percentile($values,$p){$sorted=@($values|Sort-Object);$sorted[[Math]::Ceiling($p*$sorted.Count)-1]}
foreach($variant in $variants){
    $data=Get-Content -LiteralPath (Join-Path $outDir "qwen37-tool-$variant-20261006.json") -Raw | ConvertFrom-Json
    $expectedCount=if($variant -eq 'holdout'){40}else{100}
    if($data.cases.Count -ne $expectedCount){throw "incomplete_$variant"}
    foreach($r in $data.cases){
        $native=[bool]$r.native_pass;$raw=[bool]$r.success;$notes=@()
        if($variant -eq 'optimized' -and $r.id -eq 45){$native=$true;$raw=$true;$notes+='人工复核：多久后是有效澄清，自动关键词检查误判。'}
        if($variant -eq 'holdout' -and $r.id -eq 137){$raw=$true;$notes+='人工复核：已接收、正在处理中没有声称完成，自动检查误判。'}
        if($variant -eq 'final' -and $r.id -in @(3,9,10)){$raw=$false;$notes+='人工复核：工具回执是33分，原始正文说半点，数值不忠实；现有确定性时间回执保护输出准确时间。'}
        if($variant -eq 'holdout' -and $r.id -eq 136){$notes+='两项设置的首次工具和参数正确，部分失败后追加一次状态查询；按禁止额外调用的严格口径未通过，未重复写入，也未假报全部成功。'}
        $r | Add-Member reviewed_native_pass $native
        $r | Add-Member reviewed_raw_pass $raw
        $r | Add-Member manual_notes $notes
    }
    $rows=@($data.cases)
    $positive=@($rows|Where-Object {$_.expected.Count -gt 0})
    $negative=@($rows|Where-Object {$_.expected.Count -eq 0})
    $live=@($rows|Where-Object {$_.group -in @('live_time','live_random')})
    $stats=[ordered]@{variant=$variant;total=$rows.Count;native_passed=@($rows|Where-Object reviewed_native_pass).Count;raw_reply_passed=@($rows|Where-Object reviewed_raw_pass).Count
        positive_total=$positive.Count;positive_native_passed=@($positive|Where-Object reviewed_native_pass).Count
        negative_total=$negative.Count;negative_native_passed=@($negative|Where-Object reviewed_native_pass).Count
        live_readonly_cases=$live.Count;live_native_passed=@($live|Where-Object reviewed_native_pass).Count
        live_executions=@($rows|ForEach-Object {$_.executions}|Where-Object {$_.transport -eq 'live MCP'}).Count
        first_decision_p50_ms=(Percentile @($rows|ForEach-Object {$_.steps[0].first_ms}) .5)
        first_decision_p95_ms=(Percentile @($rows|ForEach-Object {$_.steps[0].first_ms}) .95)
        primary_requests=@($rows|ForEach-Object {$_.steps}).Count
        input_tokens=($rows|ForEach-Object {$_.usage}|Measure-Object prompt_tokens -Sum).Sum
        output_tokens=($rows|ForEach-Object {$_.usage}|Measure-Object completion_tokens -Sum).Sum
        reasoning_chars=($rows|Measure-Object reasoning_chars -Sum).Sum}
    $reviews += [ordered]@{variant=$variant;stats=$stats;cases=$rows}
}
$handler=Get-Content -LiteralPath (Join-Path $outDir 'qwen37-tool-handler-final-candidate-20261006.json') -Raw|ConvertFrom-Json
$guard=Get-Content -LiteralPath (Join-Path $outDir 'qwen37-tool-protection-replay-candidate-20261006.json') -Raw|ConvertFrom-Json
$regression=Get-Content -LiteralPath (Join-Path $outDir 'qwen37-tool-guard-regression-20261006.json') -Raw|ConvertFrom-Json
$review=[ordered]@{date='2026-10-06';model='qwen3.7-plus';temperature=.4;enable_thinking=$false;production_changed=$false;physical_test=$false
    method='实际阿里上游API，生产LLMProvider的原生流式tool_calls；相同100条基线和两次优化测试；最终提示词另测40条未用于调提示词的用例；人格不变，无二次润色模型或逐句语义校验。'
    limits='定向一次采样不是线上总体成功概率；设备操作、提醒和习惯使用隔离回执；真实MCP只执行时间与随机工具。工具调用决策与正文忠实度分别计分。完整线上音频和设备未验收。'
    combined_final=[ordered]@{total=140;native_passed=136;raw_reply_passed=132;note='最终100条加补充40条；98+38=136个调用决策通过；95+37=132个含原始正文通过。不能把参数保护6条回放的通过当140条端到端结果。'}
    variants=$reviews;handler=$handler;protection_replay=$guard;regression=$regression}
$review|ConvertTo-Json -Depth 60|Set-Content -LiteralPath (Join-Path $outDir 'qwen37-tool-reviewed-20261006.json') -Encoding utf8
$text=[Text.StringBuilder]::new()
[void]$text.AppendLine('# Qwen3.7 Plus 工具测试完整原话 · 2026-10-06')
[void]$text.AppendLine("`n非思考，温度0.4，沿用两种用户人格，真实阿里API。以下保留全部原始输出；没有为展示效果改写。时间、随机工具是真实MCP；提醒、习惯及硬件使用隔离回执。每条独立上下文；少量连续查询有明确记录的历史。完整正式对话处理器另列。`n")
foreach($v in $reviews){
    [void]$text.AppendLine("`n## $($v.variant)`n")
    foreach($r in $v.cases){
        [void]$text.AppendLine("### 用例 $($r.id) · $($r.group) · $($r.persona)`n")
        foreach($m in $r.history){[void]$text.AppendLine("历史 $($m.role)：$($m.content)`n")}
        [void]$text.AppendLine("用户：$($r.user)`n")
        for($i=0;$i -lt $r.steps.Count;$i++){
            $step=$r.steps[$i]
            [void]$text.AppendLine("模型第$($i+1)次输出正文：$($step.text)`n")
            [void]$text.AppendLine("结构化 tool_calls：$(ConvertTo-Json -InputObject @($step.calls) -Depth 12 -Compress)`n")
        }
        foreach($e in $r.executions){
            [void]$text.AppendLine("执行 $($e.name) [$($e.transport)] 参数：$(ConvertTo-Json -InputObject $e.arguments -Depth 12 -Compress)`n")
            [void]$text.AppendLine("回执原文：$($e.receipt_text)`n")
            if($e.protected_reply){[void]$text.AppendLine("现有确定性回执保护输出：$($e.protected_reply)`n")}
        }
        [void]$text.AppendLine("调用决策通过：$($r.reviewed_native_pass)；含正文通过：$($r.reviewed_raw_pass)。自动失败标记：$($r.reasons -join ', ')。`n")
        foreach($note in $r.manual_notes){[void]$text.AppendLine("人工复核：$note`n")}
    }
}
[void]$text.AppendLine("`n## 最终候选正式处理器链路（真实MCP，只读，未上线）`n")
foreach($r in $handler.cases){[void]$text.AppendLine("用户：$($r.user)`n`n播报正文：$($r.spoken)`n`n工具事件：$(ConvertTo-Json -InputObject @($r.tool_events) -Depth 12 -Compress)`n`n通过：$($r.success)`n")}
[void]$text.AppendLine("`n## 保护回放（真实失败提案，隔离执行器）`n")
foreach($r in $guard.cases){[void]$text.AppendLine("$(ConvertTo-Json -InputObject $r -Depth 15 -Compress)`n")}
$text.ToString()|Set-Content -LiteralPath (Join-Path $outDir 'QWEN37_TOOL_FULL_TRANSCRIPTS_20261006.md') -Encoding utf8
$report=@'
# Qwen3.7 Plus 工具可靠性测试 · 2026-10-06

建议作为非思考主模型候选，必须搭配执行层与真实回执保护。单靠提示词仍不可靠。没有改用户人格，没有二次润色模型，没有逐句语义校验，没有切换正式服务。

相同100条用例的调用决策通过：基线93/100，首轮优化人工复核95/100，最终提示词98/100。决定是否调用、名称与参数、依赖顺序、是否额外调用一并计分；不是只看是否输出函数名。明确且参数充分的68条，最终调用决策68/68；32条否定/假设/缺参数/缺能力通过30/32。

包含原始正文的忠实度后：基线90/100，首轮优化人工复核94/100，最终95/100。最终除了两条误调用外，三条时间正文把33分说成半点，不能算正文准确。现有确定性时间回执保护会直接输出准确时间，不使用这段模型转述。

最终提示词另测40条未用于调提示词的新输入：调用决策38/40；含正文37/40。已接收、正在处理中这条人工复核通过，自动关键词误判没有覆盖正在处理中。两项部分失败后追加状态查询按禁止额外调用的严格口径未通过；该查询没有重复写入，也没有假报全部成功。另外空回执后说已完成、把用户120改成100未通过。

最终两批合计：调用决策136/140（97.1%）；含原始正文132/140（94.3%）。这些是本轮定向测试比例，不能估计线上所有自然语言的真实成功概率。原100条用于修订提示词，另40条才是未用于修订的补充样本。

真实MCP：最终100条中20条时间查询与8条随机请求，工具决策28/28，通过真实传输执行32次（双城市请求有两个调用）；补充测试8条真实只读请求通过8/8。提醒、习惯和设备设置只验证结构化调用与隔离回执，没有创建客户提醒或操作硬件。未验证真实提醒的时间解析、持久化、到点触发及设备操作结果。

正式ConnectionHandler + ToolManager + ServerMCPExecutor + 原有回执保护：最终候选11/11，通过8次真实世界时间执行（3显式、2口语、双城市2次，合计应以原始事件数核对），无硬件操作。此处只有时间及缺能力拒绝的窄范围，不可当所有工具端到端成功率。

参数保护发现实际漏洞：把音量设置为120，直接调。模型改成100，原控制层因为附加直接调未识别整个句子，放行了100。候选修复保留每个清晰分句中的明确目标，即使整句不能快路由，模型参数也必须与目标一致；否则拒绝执行，不静默截断。用户人格和相对调整路径不变。

六条隔离保护回放：缺时间猜十分钟、假设句创建提醒、120改100、空回执、排队回执、离线回执全部被阻断或输出未确认；这是安全行为验收，不是六条操作成功。122条回归全部通过；候选保护下真实模型的处理器11条也全部通过。

最终工具提示词要求：本轮目录唯一有效；真实请求才调用；目录外函数不调用；提醒/随机等不能只口头答应；调用前不输出已完成；缺参数问清、越界值不擅自替换；相对设置先读状态；重新查询用新回执；失败和部分成功分别说明。

环境：qwen3.7-plus，temperature=0.4，enable_thinking=false；340条原生测试观察到的推理文本均为0字符。现有正式网关令牌不允许该模型，所以本次使用服务器现有阿里上游密钥直接调用，没有修改网关、令牌、模型默认配置或正式源码。切换时还需要正确配置3.7 Plus的非思考参数及网关许可。

完整原话：QWEN37_TOOL_FULL_TRANSCRIPTS_20261006.md；完整最终提示词：qwen37-tool-prompt-final-20261006.txt；逐条人工审查：qwen37-tool-reviewed-20261006.json。候选代码及回归在tools/natural-dialogue-presets-20261005/qwen37-tool-guard/。没有承诺100%，没有实机、ASR或实际声音验收，也没有将本次结果当自然聊天通过。
'@
$actualEvents=@($handler.cases|ForEach-Object {$_.tool_events}).Count
$report=$report.Replace('通过8次真实世界时间执行（3显式、2口语、双城市2次，合计应以原始事件数核对）',"通过$actualEvents 次真实世界时间执行")
$report|Set-Content -LiteralPath (Join-Path $outDir 'QWEN37_TOOL_RETEST_20261006.md') -Encoding utf8
if($CanvasPath){
    $inline=$review|ConvertTo-Json -Depth 60 -Compress
    $tsx=@'
import {useState,useHostTheme,H1,H2,Divider} from "cursor/canvas";
const DATA=__DATA__;
export default function QwenToolReview(){
 const theme=useHostTheme();const [variant,setVariant]=useState("final");const [failOnly,setFailOnly]=useState(true);
 const current=DATA.variants.find(v=>v.variant===variant)!;
 const rows=current.cases.filter(r=>!failOnly||!r.reviewed_raw_pass);
 const style={background:theme.bg.editor,color:theme.text.primary,border:`1px solid ${theme.stroke.primary}`,padding:8};
 return <div style={{background:theme.bg.editor,color:theme.text.primary,padding:24,maxWidth:1060,margin:"auto"}}>
  <H1>Qwen3.7 Plus 工具可靠性复测</H1>
  <p style={{color:theme.text.secondary}}>2026-10-06 · 真实阿里API · 非思考 · 温度0.4 · 用户人格未改 · 正式服务未切换</p>
  <H2>调用决策提高到98/100，原始正文准确95/100</H2>
  <p>补充40条：调用决策38/40，含正文37/40。最终两批合计136/140与132/140；这是定向测试比例，不是线上总体可靠性。</p>
  <p>真实处理器窄范围工具链路11/11；候选保护回归122/122。设备、提醒和习惯用隔离回执；实际MCP只执行时间与随机工具，没有实机验收。</p>
  <p>已修复候选保护：120不能被模型擅自改成100。旧保护会放行，该修复目前仅在隔离环境验证。缺时间、假设句、空回执均不能说操作完成。</p>
  <Divider/>
  <div style={{display:"flex",gap:16,alignItems:"center",margin:"18px 0",flexWrap:"wrap"}}>
   <select aria-label="测试批次" style={style} value={variant} onChange={e=>setVariant(e.target.value)}><option value="current">基线100条</option><option value="optimized">首轮优化100条</option><option value="final">最终提示词100条</option><option value="holdout">新增补充40条</option></select>
   <label><input type="checkbox" checked={failOnly} onChange={e=>setFailOnly(e.target.checked)}/>只看未通过原话</label>
  </div>
  <p>本批调用决策 {current.stats.native_passed}/{current.stats.total}；含正文 {current.stats.raw_reply_passed}/{current.stats.total}。首个模型决策p50/p95 {current.stats.first_decision_p50_ms}/{current.stats.first_decision_p95_ms}ms；不是设备首声。</p>
  {rows.map(r=><section key={r.id} style={{padding:"18px 0",borderBottom:`1px solid ${theme.stroke.primary}`}}>
   <H2>用例{r.id} · {r.group}</H2><p style={{color:theme.text.secondary}}>人格：{r.persona} · 调用决策{r.reviewed_native_pass?"通过":"未通过"} · 含正文{r.reviewed_raw_pass?"通过":"未通过"}</p>
   {r.history?.map((m,i)=><p key={i}>历史 {m.role}：{m.content}</p>)}<p>用户：{r.user}</p>
   {r.steps.map((s,i)=><div key={i}><p style={{whiteSpace:"pre-wrap"}}>模型第{i+1}次正文：{s.text||"（仅结构化调用）"}</p>{s.calls.map((c,j)=><p key={j}>tool_calls：{c.name} {c.arguments}</p>)}</div>)}
   {r.executions.map((e,i)=><div key={i}><p style={{whiteSpace:"pre-wrap",color:theme.text.secondary}}>回执 [{e.transport}] {e.name}：{e.receipt_text}</p>{e.protected_reply&&<p>原有回执保护：{e.protected_reply}</p>}</div>)}
   {r.manual_notes.map((note,i)=><p key={i} style={{color:theme.accent.primary}}>人工复核：{note}</p>)}
  </section>)}
 </div>;
}
'@
    $tsx.Replace('__DATA__',$inline)|Set-Content -LiteralPath $CanvasPath -Encoding utf8
}
$reviews|ForEach-Object {$_.stats}|ConvertTo-Json -Depth 10
