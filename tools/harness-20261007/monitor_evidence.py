import collections,json,math,sys,time
from pathlib import Path
root=Path(__file__).parent/sys.argv[1]
def p95(v):return round(sorted(v)[max(0,math.ceil(.95*len(v))-1)],2) if v else None
rows={}
for name in ('single','complex','holdout'):
    f=root/(name+'.jsonl');r=[json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else [];rows[name]=r
    print(json.dumps({'suite':name,'n':len(r),'candidate_n':sum(x['chain']=='candidate' for x in r),'candidate_failed':[{'id':x['id'],'repeat':x['repeat']} for x in r if x['chain']=='candidate' and not x['passed']]}))
pairs={s:{(r['id'],r['repeat']):r for r in rows['single'] if r['chain']==s and r['group']!='negative'} for s in ('baseline','candidate')}
matched=[(pairs['baseline'][k],pairs['candidate'][k]) for k in pairs['baseline'].keys()&pairs['candidate'].keys()]
normal=[(b,c) for b,c in matched if len(c.get('calls',[]))<=1 and not c.get('outcome',{}).get('repairs')]
b=p95([b['elapsed_ms'] for b,c in normal]);c=p95([c['elapsed_ms'] for b,c in normal])
print(json.dumps({'partial_normal_pairs':len(normal),'baseline_p95_ms':b,'candidate_p95_ms':c,'ratio':round(c/b,3) if b and c else None,'not_final_gate':True}))
for f in root.glob('*jobs-results.json'):print(json.dumps({'job_file':f.name,'results':json.loads(f.read_text())}))
