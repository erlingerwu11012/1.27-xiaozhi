import json, html
from pathlib import Path

out = Path('docs/natural-dialogue-presets-20261005/dialogue-records')
out.mkdir(parents=True, exist_ok=True)
data = json.loads(Path('docs/natural-dialogue-presets-20261005/long-dialogue-acceptance.json').read_text(encoding='utf-8'))
css = '''body{margin:0;background:#eef2f7;color:#1e293b;font:18px/1.65 "Microsoft YaHei",sans-serif}main{max-width:980px;margin:28px auto;background:white;padding:28px 40px;border-radius:18px}h1{font-size:27px;margin:0}h2{font-size:21px}header p{font-size:15px;color:#526277;margin:8px 0}.persona{background:#f1f5f9;padding:12px 18px;border-radius:10px;font-size:16px}.round{border-top:1px solid #e2e8f0;margin-top:18px;padding-top:12px}.num{font-size:13px;color:#64748b}.user,.assistant{padding:10px 16px;border-radius:10px;margin:8px 0;white-space:pre-wrap}.user{background:#eaf2ff}.assistant{background:#f3f5f8}.tool{font-size:14px;white-space:pre-wrap;background:#fff7df;padding:12px}.warning{background:#fff0ed;color:#9c3226;padding:12px;font-size:15px}nav a{margin-right:18px}footer{font-size:14px;color:#64748b;margin-top:20px}'''
md = ['# 完整连续对话原始记录', '\n正式默认模型 qwen3.8-flash，温度0.4。两套人格各12轮，保留上下文；没有二次润色，没有实机语音测试。用户输入为验收脚本编写，模型输出原样保存。\n']
links=[]
for profile in data['profiles']:
    md += ['## '+profile['name'], '\n人格：'+profile['prompt']+'\n']
    for row in profile['turns']:
        md += [f"### 第{row['turn']}轮", '\n用户：'+row['user'], '\n模型：'+row['raw_assistant']+'\n']
        for event in row['tool_events']:
            md += ['工具：'+event['name']+' '+json.dumps(event['arguments'],ensure_ascii=False), '\n实际返回：'+event['actual_result']+'\n']
    for part in range(2):
        filename=f"{profile['id']}-{part+1}.html"
        links.append((filename, profile['name']+f' · 第{part*6+1}—{part*6+6}轮'))
        blocks=[]
        for row in profile['turns'][part*6:(part+1)*6]:
            tool=''.join('<div class="tool">真实MCP调用：'+html.escape(e['name']+' '+json.dumps(e['arguments'],ensure_ascii=False)+'\n实际返回：'+e['actual_result'])+'</div>' for e in row['tool_events'])
            blocks.append(f'<section class="round"><div class="num">第{row["turn"]}轮</div><div class="user"><b>测试输入</b>　{html.escape(row["user"])}</div>{tool}<div class="assistant"><b>模型原始回复</b>　{html.escape(row["raw_assistant"])}</div></section>')
        warning='<div class="warning">保留失败输出：第11轮变成用户意图摘要；第12轮工具返回11:49，模型却说18:49。本组不能判为通过。</div>' if profile['id']=='existing-playful' and part==1 else ''
        content=f'<!doctype html><html lang="zh"><meta charset="utf-8"><title>{profile["name"]}完整记录</title><style>{css}</style><main><header><h1>连续对话测试 · 原始记录截图</h1><h2>{profile["name"]} · 第{part*6+1}—{part*6+6}轮 / 共12轮</h2><p>2026-10-05 · qwen3.8-flash · 温度0.4 · 称呼：主人</p><p>正式模型与平台提示词；上下文连续保留；无二次润色；文字输入，未做实机语音验收。</p><div class="persona">用户人格：{html.escape(profile["prompt"])}</div></header>{warning}{"".join(blocks)}<footer>测试问题由脚本编写；模型回复逐字来自 long-dialogue-acceptance.json，未挑选或修改。截图为记录排版页面，不是产品聊天界面。</footer></main></html>'
        (out/filename).write_text(content,encoding='utf-8')
(out/'index.html').write_text('<!doctype html><meta charset="utf-8"><style>'+css+'</style><main><h1>完整连续对话记录</h1><p>两套人格各12轮，原样保留全部输出，包括失败。点击查看：</p>'+''.join(f'<p><a href="{f}">{html.escape(t)}</a></p>' for f,t in links)+'</main>',encoding='utf-8')
(out/'full-dialogue.md').write_text('\n'.join(md),encoding='utf-8')
print(out.resolve())
