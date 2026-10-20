import json
from pathlib import Path
p=Path(__file__).parent/'final-cases.json';a=json.loads(p.read_text(encoding='utf-8'));assert len(a)==240
scenes=[('自行车','修车店','家里'),('快递','驿站','办公室'),('眼镜','眼镜店','家里'),('电脑','维修店','办公室'),('衣服','干洗店','家里'),('相机','朋友家','工作室'),('书','图书馆','家里'),('雨伞','公司','家里'),('行李','酒店','车站'),('文件','打印店','办公室')]
for i,(thing,old,new) in enumerate(scenes):
 qs=[(f'我的{thing}还在{old}，我还没有拿回来。这只是闲聊，不要替我安排。',[]),(f'更新一下，我刚把{thing}拿回来了，现在放在{new}。',[]),('别再追问，也不要开玩笑，你就正常接着说。',[]),(f'只根据我这段话，{thing}现在在哪里？',[new])]
 for q,required in qs:a.append({'id':len(a)+1,'query':q,'tool':None,'arguments':{},'group':'chat','session':'chat-supplement-'+str(i),'required':required,'holdout':True})
p.write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
