from pathlib import Path
import json,shutil,time
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix)
 if p.exists():p.rename(S/('resume-card-progress-failures-'+suffix))
p=S/'final-cases.json';rows=json.loads(p.read_text());shutil.copy2(p,S/'before-card-progress-cases.json')
for r in rows:
 if r['id']=='new-52':r['required']=[x+'|运输中|运输途中|路上' for x in r['required']]
 if r['id']=='holdout-22':r['independent_holdout']=False;r['development_from_failed_holdout']=True
queries=[('查一下卡片关没关','reminder_get_current'),('你看下这张卡片还挂在屏幕上没','reminder_get_current'),('现在音量是多少，帮我看一眼','self_get_device_status'),('亮度目前在哪一档，查查看','self_get_device_status'),('查查屏幕上这张卡的内容','reminder_get_current'),('这会儿提醒卡片是不是还在显示','reminder_get_current'),('我问的是当前声音多大，查一下','self_get_device_status'),('看看当前屏幕亮度的状态','self_get_device_status')]
for i,(q,t) in enumerate(queries):rows.append({'id':'fresh-read-'+str(i+1),'query':q,'tool':t,'arguments':{},'group':'fresh','holdout':True,'independent_holdout':True})
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2));(S/'card-progress-review.json').write_text(json.dumps({'failed_originals_retained':True,'manual_failure':'reg-164 changed half to majority','oracle_false_positive':{'id':'new-52','reason':'in transit is semantically equivalent to not delivered; retained same completion truth requirement'},'former_holdout_reclassified':'holdout-22','new_independent_samples':8,'total':len(rows),'independent':sum(bool(x.get('independent_holdout')) for x in rows)},indent=2));print('cases',len(rows))
