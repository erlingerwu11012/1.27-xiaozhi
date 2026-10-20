"""Export every real response, including failures, as readable UTF-8 Markdown."""
import json,statistics
from pathlib import Path
root=Path('docs/natural-dialogue-presets-20261005')
lines=['# 对话优化完整测试记录',
       '\n测试输入均为脚本编写，回复为真实模型原文。没有客户历史、二次润色或实机麦克风验收。完成调用不等于聊天质量通过。\n']
stats=[]
for filename,label in [('dialogue-fix-model-comparison.json','第一轮：旧规则基线与三个模型对比'),
                       ('dialogue-fix-heldout.json','第二轮：新话题复测，语音规则冲突尚未消除'),
                       ('dialogue-fix-final.json','第三轮：消除语音动作标签引导后的最终候选'),
                       ('dialogue-fix-thinking-probe.json','同一个Max主模型开启思考模式对照')]:
    data=json.loads((root/filename).read_text(encoding='utf-8'))
    lines+=['## '+label, '\n原始文件：'+filename+'\n']
    if 'dialogues' in data:
        for d in data['dialogues']:
            lines += ['### '+d['model']+' / '+d.get('revision','')+' / '+d['persona'], '\n人格原文：'+d.get('persona_prompt','')+'\n']
            for r in d['turns']:
                lines += [f"第{r['turn']}轮\n", '用户：'+r['user']+'\n', '模型：'+r.get('assistant','[请求失败]')+'\n']
                if r.get('tool_proposals'):lines+=['工具提议（未执行）：'+json.dumps(r['tool_proposals'],ensure_ascii=False)+'\n']
            stats.append({'report':filename,'model':d['model'],'persona':d['persona'],'turns':len(d['turns']),
                          'median_total_ms':round(statistics.median(r['elapsed_ms'] for r in d['turns'] if 'elapsed_ms' in r))})
        for r in data.get('boundaries',[]):
            lines+=['### 边界场景：'+r['model']+' / '+r['case'], '\n用户：'+r['user']+'\n','模型：'+r.get('assistant','[请求失败]')+'\n']
    else:
        for r in data['turns']:
            lines += [f"第{r['turn']}轮\n",'用户：'+r['user']+'\n','模型：'+r.get('assistant','[请求失败]')+'\n',f"总响应时间：{r.get('elapsed_ms')}毫秒\n"]
(root/'dialogue-fix-full-conversations.md').write_text('\n'.join(lines),encoding='utf-8')
(root/'dialogue-fix-latency-summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'raw_primary_comparison_calls':sum(json.loads((root/name).read_text(encoding='utf-8')).get('calls',0) for name in ['dialogue-fix-model-comparison.json','dialogue-fix-heldout.json','dialogue-fix-final.json'])+8,'exported_profiles':len(stats)},ensure_ascii=False))
