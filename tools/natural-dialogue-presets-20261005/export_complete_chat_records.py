"""Export every original response, including rejected candidates and failures."""
import json
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
names=sorted(p.stem for p in OUT.glob('complete-chat-*.json'))
for name in names:
 p=OUT/(name+'.json')
 if not p.exists(): continue
 data=json.loads(p.read_text())
 if 'dialogues' not in data:continue
 lines=[f'# {name} 完整对话记录','',
    '所有用户输入均为合成验收内容。以下展示全部原始结果；程序完成或校验空数组不代表聊天质量自动通过。',
    '未接物理设备、未访问客户会话、未执行硬件写操作。', '',
    f"完成状态：{data.get('completed')}；聊天轮数：{data.get('calls')}。",'']
 for d in data['dialogues']:
    lines.extend([f"## {d['id']}",''])
    for t in d['turns']:
     lines.extend([f"### 第 {t['turn']} 轮",'',f"用户：{t['user']}",'',
        f"实际送入TTS的正文：{t['assistant']}",'',
        f"总处理时间：{t['elapsed_ms']}ms；模型请求：{t.get('request_count')}；工具提议：{len(t.get('tool_proposals',[]))}。",''])
     gate=t.get('response_check') or {}
     if gate.get('fallback'): lines.extend(['**此轮降级未接住话题，计为聊天质量失败。**',''])
     if not t.get('response_model'):lines.extend(['**未确认真实上游响应；不能计为模型聊天验收通过。**',''])
     if 'length' in t.get('finish_reasons',[]):lines.extend(['**上游输出被截断，计为失败。**',''])
     for idx, draft in enumerate(t.get('generated_attempts',[]),1):
      lines.extend([f'第{idx}次原始主模型输出：{draft}',''])
     if gate.get('violations'):
      lines.extend(['程序判定记录：'+json.dumps(gate,ensure_ascii=False),''])
 (OUT/(name+'-conversations.md')).write_text('\n'.join(lines))
print('exported all available records')
