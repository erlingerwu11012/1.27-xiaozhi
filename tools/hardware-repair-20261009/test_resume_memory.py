import bootstrap,json
from bootstrap import stage,budget
from core.utils.tool_harness.memory_policy import memory_intent
from core.utils.tool_harness.runtime import memory_read_request
from core.utils.tool_harness.reply_composer import unsafe
from core.utils.tool_harness.models import StepResult
cases=[('我现在改喝绿茶了，把喜欢咖啡那条记忆更新一下','correct'),('之前台灯叫什么那条记忆帮我忘了','forget'),('我想查现在喝什么，并没有要求你更正','read'),('你记着我喝哪种饮料了吗，查一下','read'),('我就问问爱喝啥，你更正什么记忆啊','read'),('翻出小时候的照片，有些场景都忘记了','read'),('我以前那个地方的名字忘了','read'),('别给我乱改记忆','read'),('你删除那条记忆了吗','read'),('你是不是把咖啡的记忆改了','read'),('如果我说把记忆改成绿茶会怎样','read'),('能不能帮我把台灯那条记忆删掉','forget'),('把我的饮料偏好改成红茶','correct'),('记忆更正是什么意思','read'),('台灯的记忆别记着了','forget'),('九成半，声音改一下','read'),('不是啊，我现在不喝咖啡了，你改一下','correct'),('我忘记了台灯叫什么','read')]
rows=[]
for q,wanted in cases:
 budget.reserve('case','resume-memory-authority:'+q);actual=memory_intent(q);rows.append({'query':q,'wanted':wanted,'actual':actual,'passed':actual==wanted})
for q in ['我想查现在喝什么，并没有要求你更正','你记着我喝哪种饮料了吗，查一下']:
 budget.reserve('case','resume-memory-query:'+q);rows.append({'query':q,'passed':memory_read_request(q)==q})
r=StepResult(tool='memory_search',state='completed',call_id='test',arguments={},reply='喜欢咖啡',payload={'text':'我喜欢咖啡'})
for q,wanted in [('好的，我已经把关于台灯的记忆删除了',True),('你这次只是在查询，我没有修改记忆',False),('已经替你更正为绿茶了',True),('你之前喜欢咖啡',False)]:
 budget.reserve('case','resume-memory-claim:'+q);rows.append({'speech':q,'passed':unsafe(q,[r])==wanted})
summary={'tests':len(rows),'passed':all(x['passed'] for x in rows),'rows':rows};(stage/'resume-memory-regression.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));assert summary['passed']
