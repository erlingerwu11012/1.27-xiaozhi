const fs=require('fs');
const root='docs/natural-dialogue-presets-20261005/';
const d=JSON.parse(fs.readFileSync(root+'qwen-paired-tool-results-20261006.json','utf8'));
for(const m of d.models){
 const rows=d.cases.filter(r=>r.model===m);
 const positive=rows.filter(r=>r.expected.length),negative=rows.filter(r=>!r.expected.length);
 const count=a=>[a.filter(r=>r.native_pass).length,a.length];
 console.log(m,JSON.stringify({rounds:[1,2,3].map(t=>[t,...count(rows.filter(r=>r.trial===t))]),positive:count(positive),negative:count(negative),reasons:Object.fromEntries([...new Set(rows.flatMap(r=>r.reasons))].map(k=>[k,rows.filter(r=>r.reasons.includes(k)).length]))}));
}
console.log('payloads',d.pairs.filter(p=>p.identical_initial_payload).length,'paired',d.pairs.reduce((a,p)=>{const k=(p.plus_pass?'p':'x')+(p.flash_pass?'f':'x');a[k]=(a[k]||0)+1;return a;},{}));
const bad=d.cases.filter(r=>!r.native_pass&&r.model===d.models[1]);
for(const reason of ['wrong_tool_or_arguments','unrequested_call','unknown_tool_or_invalid_schema']){
 console.log('FAILURES',reason);
 console.log(JSON.stringify(bad.filter(r=>r.reasons.includes(reason)).map(r=>({id:r.id,trial:r.trial,u:r.user,e:r.expected,s:r.steps})),null,1));
}
console.log('MISSING',bad.filter(r=>r.reasons.includes('missing_native_call')).map(r=>[r.id,r.trial,r.user,r.steps[r.steps.length-1].text]));
const p=JSON.parse(fs.readFileSync(root+'qwen-paired-tool-pack-20261006.json','utf8'));
console.log('REMINDER DEFINITION',p.real_catalog.find(t=>t.function.name==='add_reminder'));
