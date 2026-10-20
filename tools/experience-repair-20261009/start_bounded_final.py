from pathlib import Path
import json,time,subprocess
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log','final-summary.json']:
 p=S/n
 if p.exists():
  d=S/('aborted-eighth-'+n);assert not d.exists();p.rename(d)
old=json.loads((S/'final-cases.json').read_text());(S/'prior-final-cases-319.json').write_text(json.dumps(old,ensure_ascii=False,indent=2));a=old[:259]+[{**x,'independent_holdout':False,'prior_failed_holdout':True} for x in old if x.get('session')=='release-holdout-card']
def add(q,session,**kw):a.append({'id':700+len(a)-262,'query':q,'tool':None,'arguments':{},'group':'chat','session':session,'holdout':True,'independent_holdout':True,**kw})
scenes=[('洗衣卡','玄关柜','卡包'),('眼镜布','茶几','眼镜盒'),('小型三脚架','桌角','摄影包'),('硬盘盒','书桌','抽屉'),('旧唱片','客厅','收纳柜'),('笔记本支架','卧室','办公桌'),('毛线帽','衣架','衣柜'),('停车票','口袋','文件袋'),('相机背带','沙发','旅行包'),('备用数据线','床头','工具盒'),('木质书签','书柜','笔袋'),('便携风扇','窗台','背包'),('收纳篮','阳台','厨房'),('旅行枕','沙发','行李箱'),('钥匙挂绳','餐桌','门口柜'),('体温计','抽屉','药箱'),('读卡器','电脑旁','电脑包'),('文具剪刀','桌面','笔筒'),('折叠袋','鞋柜','手提包'),('保修单','钱包','资料夹')]
for i,(item,origin,target) in enumerate(scenes):
 name='chat-final-proof-'+str(i)
 add(f'{item}之前放在{origin}。就聊些小事，别老反问，也别替我安排。',name)
 add(f'我刚把{item}挪到了{target}，{origin}那里已经没有了。',name)
 add(f'根据我刚才说的，{item}现在在哪？直接回答。',name,required=[target])
assert len(a)==322 and sum(bool(x.get('independent_holdout')) for x in a)==60
(S/'final-cases.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
(S/'aborted-eighth-note.json').write_text(json.dumps({'reason':'319 complete,317 passed. Two failures preserved: pure list missing planner authority fields; correction reread blocked as duplicate. Fixed and verified with actual MCP transport,49 latest regressions pass. Failed card session retained in full,60 new independent fact/feedback holdouts.','time':time.time()}))
(S/'quality-priority-final-authorization.json').write_text(json.dumps({'case_limit':4300,'model_limit':2200,'reason':'User prioritizes repairing bugs and experience; counters retained including free replays and failed batches. Final bounded paid batch, no extra background paid requests.','time':time.time()}))
f=(S/'final-console.log').open('w');p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_final.py')],cwd=S,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'final-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}));print(json.dumps({'pid':p.pid,'cases':322,'fresh_holdout':60}))
