param([string]$CanvasPath)
$ErrorActionPreference = 'Stop'
$outDir = Join-Path $PSScriptRoot '../../docs/natural-dialogue-presets-20261005'
$chat = Get-Content -LiteralPath (Join-Path $outDir 'deepseek-retest-chat-20261006.json') -Raw | ConvertFrom-Json
$mcp = Get-Content -LiteralPath (Join-Path $outDir 'deepseek-retest-mcp-20261006.json') -Raw | ConvertFrom-Json
$native = Get-Content -LiteralPath (Join-Path $outDir 'deepseek-retest-native-20261006.json') -Raw | ConvertFrom-Json
$baseline = Get-Content -LiteralPath (Join-Path $outDir 'prompt-only-reviewed-results.json') -Raw | ConvertFrom-Json
$rows = @($chat.dialogues | ForEach-Object {$_.turns})
if (!$chat.completed -or $rows.Count -ne 200) { throw 'chat_test_incomplete' }
function Percentile($values, $p) { $sorted = @($values | Sort-Object); $sorted[[Math]::Ceiling($p * $sorted.Count)-1] }
$stats = [ordered]@{
    turns=$rows.Count; input_tokens=$chat.usage.input_tokens; output_tokens=$chat.usage.output_tokens
    first_text_p50_ms=(Percentile $rows.first_primary_text_ms .5)
    first_text_p95_ms=(Percentile $rows.first_primary_text_ms .95)
    first_tts_enqueue_p50_ms=(Percentile $rows.first_tts_enqueue_ms .5)
    first_tts_enqueue_p95_ms=(Percentile $rows.first_tts_enqueue_ms .95)
    max_input_tokens=($rows.usage.prompt_tokens | Measure-Object -Maximum).Maximum
    chat_tool_proposal_turns=@($rows | Where-Object {$_.tool_proposals.Count -gt 0}).Count
    context_states=@($rows.context_status | Sort-Object -Unique)
    summary_versions=@($rows.summary_version | Sort-Object -Unique)
    mcp_passed=@($mcp.cases | Where-Object success).Count; mcp_total=$mcp.cases.Count
    mcp_executions=@($mcp.cases | ForEach-Object {$_.tool_events}).Count
}
$recall = @($baseline.recall | Where-Object {$_.id -like 'prompt_only/*'} | ForEach-Object {
    $reference=$_; $dialogue=$chat.dialogues | Where-Object id -eq $reference.id
    $turn=$dialogue.turns | Where-Object turn -eq $reference.turn
    $passed=$reference.id -notmatch '/0$'
    $reason=if($passed){'本条指定回忆问题的关键状态完整；不代表整段其他回复通过。'}elseif($reference.id -like '*/natural/*'){'报告已完成一半，却说正文还没开始，存在事实冲突。'}else{'说正文还没动，未限定剩余部分或昨天，与已完成一半产生范围歧义；按严格明确表达口径不通过。'}
    [ordered]@{id=$reference.id;turn=$reference.turn;expected=$reference.expected;assistant=$turn.assistant;passed=$passed;reason=$reason}
})
$stats.strict_recall_passed=@($recall | Where-Object passed).Count
$stats.strict_recall_total=$recall.Count
$issues=@(
    @{id='prompt_only/natural/0';turn=7;reason='已经写好一半，仍说正文还没开始。'},
    @{id='prompt_only/natural/0';turn=10;reason='用户已纠正时间范围，最终回答仍重复正文还没开始。'},
    @{id='prompt_only/existing-playful/0';turn=7;reason='已完成一半被概括为正文还没开始。'},
    @{id='prompt_only/existing-playful/0';turn=10;reason='最终正文还没动缺少时间/剩余部分限定，严格口径下有范围歧义。'},
    @{id='prompt_only/existing-playful/1';turn=2;reason='用户说可能再开、尚未确定，回复改成明天还得再来一轮。'},
    @{id='prompt_only/natural/4';turn=1;reason='擅自补出用户已空出周五。'},
    @{id='prompt_only/existing-playful/4';turn=3;reason='用户要求不提供建议，仍说等对方给准话再决定如何安排。'},
    @{id='prompt_only/existing-playful/7';turn=2;reason='用户要求暂停提问，回复说不问后立即继续提问。'},
    @{id='prompt_only/natural/8';turn=8;reason='未请求建议，仍建议换一家购买。'},
    @{id='prompt_only/existing-playful/8';turn=8;reason='未请求建议，仍建议找别家。'},
    @{id='prompt_only/natural/9';turn=1;reason='明确不要教程，仍指导先软化黄油，并推断用户不急。'},
    @{id='prompt_only/existing-playful/9';turn=1;reason='明确不要教程，仍建议等待黄油软化。'}
)
$review=[ordered]@{date='2026-10-06';model=$chat.model;thinking=$chat.thinking;quality_passed=$false
    method='与之前Qwen同样的100个输入、两个人格、新提示词和生产处理器；现有官方DeepSeek渠道密钥直连；非思考；温度0.4；没有逐句校验、重答、二次润色或证据注入。'
    limitations='一次采样，只有18条指定回忆题计分；失败例子不是全量错误标注，不可推导线上总体错误率。TTS入队不是实际音频首声；无实机ASR或音频播放验收。原生工具5条诊断中3条真实调用、2条无调用判断，不能证明所有MCP工具可靠。'
    stats=$stats;baseline_qwen=$baseline.stats.prompt_only;recall=$recall;issues=$issues
}
$review | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $outDir 'deepseek-retest-reviewed-20261006.json') -Encoding utf8
$text=[Text.StringBuilder]::new()
[void]$text.AppendLine('# DeepSeek Flash 完整原始对话 · 2026-10-06')
[void]$text.AppendLine('')
[void]$text.AppendLine('deepseek-flash，非思考模式，temperature=0.4，新提示词，200轮；沿用用户人格，无逐句校验、二次润色。每段独立10轮。以下回复保留原文，没有为了展示效果改写。')
foreach($dialogue in $chat.dialogues){
    [void]$text.AppendLine("`n## $($dialogue.id)`n")
    [void]$text.AppendLine("人格原文：$($dialogue.persona_prompt)`n")
    foreach($turn in $dialogue.turns){
        [void]$text.AppendLine("### 第 $($turn.turn) 轮`n")
        [void]$text.AppendLine("用户：$($turn.user)`n")
        [void]$text.AppendLine("模型：$($turn.assistant)`n")
        [void]$text.AppendLine("输入 $($turn.usage.prompt_tokens) token；输出 $($turn.usage.completion_tokens) token；首文本 $($turn.first_primary_text_ms)ms；首TTS入队 $($turn.first_tts_enqueue_ms)ms；压缩状态 $($turn.context_status)。`n")
        foreach($issue in $issues | Where-Object {$_.id -eq $dialogue.id -and $_.turn -eq $turn.turn}){
            [void]$text.AppendLine("审查发现：$($issue.reason)`n")
        }
    }
}
[void]$text.AppendLine("`n## 连续工具请求链路`n")
foreach($case in $mcp.cases){
    [void]$text.AppendLine("用户：$($case.user)`n`n回复：$($case.spoken)`n`n真实工具执行数：$($case.tool_events.Count)；检查通过：$($case.success)。`n")
}
[void]$text.AppendLine("`n## 独立原生工具调用诊断`n")
foreach($case in $native.cases){
    [void]$text.AppendLine("用户：$($case.user)`n`n模型首回复：$($case.first.text)`n`n结构化工具调用：$(ConvertTo-Json -InputObject $case.first.calls -Depth 10 -Compress)`n")
    if($case.final){[void]$text.AppendLine("拿到回执后的模型回复：$($case.final.text)`n")}
}
$text.ToString() | Set-Content -LiteralPath (Join-Path $outDir 'DEEPSEEK_FLASH_FULL_TRANSCRIPTS_20261006.md') -Encoding utf8
$report=@"
# DeepSeek Flash 复测 · 2026-10-06

结论：可继续作为候选，尚未通过自然聊天验收，不建议直接切换正式主模型。

服务器现有 DeepSeek 官方渠道可用。本次实际调用 deepseek-flash，非思考模式、温度0.4，沿用新提示词及两个人格。正式服务代码、默认模型及渠道配置均未修改。

完成200轮真实回复（20段独立10轮）。输入731,022 token、输出5,969 token；单次输入最大4,262 token。所有上下文状态为idle、摘要版本为0，18万阈值的历史压缩没有触发。每轮一次请求，没有逐句校验、重答、二次润色；没有长度截断。

18条指定状态回忆题按严格明确表达口径通过16条。两条未通过都与报告已完成一半的表达有关：自然人格出现正文还没开始；原调皮人格最终说正文还没动，没有明确限定昨天或剩余部分，存在范围歧义。这不是200轮的总体正确率。

聊天中错误工具提议0/200；之前同提示词Qwen为3/200。两批均为一次采样，不能推导真实总体发生概率。

首文本p50/p95为663/846ms；首TTS入队p50/p95为906/1233ms。之前同提示词Qwen分别为503/874ms和1140/2242ms。DeepSeek本批TTS入队更快，但首文本中位数更慢。入队不是实际设备出声，且直连DeepSeek与Qwen原网关路径不同，延迟差异不能全归给模型。

原生工具独立诊断：伦敦、东京、纽约三条口语请求均真实发出get_world_time并得到MCP回执，回执后正文时间正确；缺失音量能力及用户否定查询两条无误调用。共5条，不足以宣称所有工具都可靠。

原有保护链路连续11条请求通过9条，真实执行5次时间查询。两条口语追问现在几点没有重新查询，沿用了本段前面回执的时间。这种即时连续追问当分钟内数值可能仍相同，但未满足每次新查询的新鲜回执要求；不能记为通过。

人工审查仍发现事实冲突、擅自补事实及反馈未遵守：报告已写一半变成正文没开始；明天可能开会变成明天还得开；用户要求不提问仍追问；用户不需要教程仍指导软化黄油。没有发现典型卖萌用语或动作标签，不代表自然聊天整体通过。

完整原话见同目录DEEPSEEK_FLASH_FULL_TRANSCRIPTS_20261006.md，原始数据及逐条审查保存在deepseek-retest-*.json。未进行物理设备、ASR或实际音频播放测试。
"@
$report | Set-Content -LiteralPath (Join-Path $outDir 'DEEPSEEK_FLASH_RETEST_20261006.md') -Encoding utf8
if($CanvasPath){
    $inline=[ordered]@{review=$review;dialogues=$chat.dialogues;mcp=$mcp.cases;native=$native.cases} | ConvertTo-Json -Depth 40 -Compress
    $tsx=@'
import {useState,useHostTheme,H1,H2,Text,Stack,Divider} from "cursor/canvas";
const DATA=__DATA__;
export default function DeepSeekReview(){
 const theme=useHostTheme();
 const [selected,setSelected]=useState("prompt_only/existing-playful/0");
 const [pane,setPane]=useState("chat");
 const dialogue=DATA.dialogues.find(d=>d.id===selected)!;
 const selectStyle={background:theme.bg.editor,color:theme.text.primary,border:`1px solid ${theme.stroke.primary}`,padding:8,maxWidth:"100%"};
 return <div style={{background:theme.bg.editor,color:theme.text.primary,padding:24,maxWidth:1040,margin:"auto"}}>
  <H1>DeepSeek Flash 实际对话复测</H1>
  <p style={{color:theme.text.secondary}}>2026-10-06 · 服务器官方接口 · 非思考模式 · 温度0.4 · 新提示词 · 完整原话</p>
  <H2>完成200轮，尚未通过自然聊天验收</H2>
  <p>聊天误选工具0/200；指定回忆题16/18（含一条范围歧义未通过）；保护链路9/11；独立原生工具诊断三次真实调用。</p>
  <p>首文本p50/p95：663/846ms；首TTS入队：906/1233ms。入队不是设备首声。输入731,022、输出5,969 token；最大单次输入4,262；没有历史压缩。</p>
  <p style={{color:theme.text.secondary}}>一次采样；指定子集不能当整体正确率。人格原文未改；无逐句校验、二次润色；正式默认模型未切换。</p>
  <Divider/>
  <div style={{display:"flex",gap:12,flexWrap:"wrap",margin:"18px 0"}}>
   <select aria-label="记录类型" value={pane} onChange={e=>setPane(e.target.value)} style={selectStyle}><option value="chat">完整连续聊天</option><option value="mcp">连续工具请求</option><option value="native">原生结构化调用</option></select>
   {pane==="chat"&&<select aria-label="选择对话" value={selected} onChange={e=>setSelected(e.target.value)} style={selectStyle}>{DATA.dialogues.map(d=><option key={d.id} value={d.id}>{d.persona==="existing-playful"?"原调皮人格":"自然人格对照"} · 场景{d.scenario+1}</option>)}</select>}
  </div>
  {pane==="chat"?<><p style={{color:theme.text.secondary}}>人格原文：{dialogue.persona_prompt}</p>{dialogue.turns.map(t=><section key={t.turn} style={{padding:"18px 0",borderBottom:`1px solid ${theme.stroke.primary}`}}><H2>第{t.turn}轮</H2><p>用户：{t.user}</p><p style={{whiteSpace:"pre-wrap"}}>模型：{t.assistant}</p>{DATA.review.issues.filter(i=>i.id===selected&&i.turn===t.turn).map((i,k)=><p key={k} style={{color:theme.accent.primary}}>审查发现：{i.reason}</p>)}<p style={{color:theme.text.tertiary,fontSize:12}}>输入{t.usage.prompt_tokens} / 输出{t.usage.completion_tokens} token · 首文本{t.first_primary_text_ms}ms · TTS入队{t.first_tts_enqueue_ms}ms</p></section>)}</>:pane==="mcp"?DATA.mcp.map((c,k)=><section key={k} style={{padding:"18px 0",borderBottom:`1px solid ${theme.stroke.primary}`}}><H2>{c.user}</H2><p>{c.spoken}</p><p>实际执行{c.tool_events.length}次；{c.success?"通过":"未通过：没有重新查询"}</p></section>):DATA.native.map((c,k)=><section key={k} style={{padding:"18px 0",borderBottom:`1px solid ${theme.stroke.primary}`}}><H2>{c.user}</H2><p>{c.first.text}</p>{c.first.calls.map((a,j)=><p key={j}>结构化调用：{a.name} {a.arguments}</p>)}{c.final&&<p>真实回执后的回复：{c.final.text}</p>}</section>)}
 </div>;
}
'@
    $tsx.Replace('__DATA__',$inline) | Set-Content -LiteralPath $CanvasPath -Encoding utf8
}
$stats | ConvertTo-Json -Depth 6 -Compress
