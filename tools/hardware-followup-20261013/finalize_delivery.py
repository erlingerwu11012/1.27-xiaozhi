from pathlib import Path
import json,hashlib,shutil,zipfile,collections,datetime
S=Path(__file__).resolve().parent;ROOT=S.parents[1];D=S/'delivery';E=D/'evidence'
manifest=json.loads((E/'final-source-freeze.json').read_text());source_files=manifest['changed_source']
with zipfile.ZipFile(D/'server-source-delta.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name in source_files:
  p=S/'work'/name;assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['candidate_work_hashes'][name],name;z.write(p,'runtime/'+name)
 for p in (S/'java').rglob('*.java'):z.write(p,'java/'+str(p.relative_to(S/'java')).replace('\\','/'))
 z.write(E/'api-package-evidence-05.json','api-package-evidence-05.json')
 z.write(E/'final-source-freeze.json','final-source-freeze.json')
rows=list(map(json.loads,(E/'final09-results.jsonl').read_text().splitlines()))
counts=collections.Counter(r.get('origin_evidence') or 'final09' for r in rows)
v=['# 版本与证据映射','','181轮业务证据按原执行记录复用，不能当成同一最终版本全量重跑。','']
for version,count in sorted(counts.items()):v.append(f'- {version}：{count}轮，完整源哈希见evidence/{version}-freeze.json。')
v+=['','部署冻结见evidence/final-source-freeze.json。final09之后仅runtime.py与reply_composer.py两处回复保护变更，18个受影响位置单独补验；其他业务证据未重新标记为新执行。','', 'quality01–07记录的是逐步修复中的上下文／可信结果回放；没有各批完整独立源码冻结包。最终部署源码已冻结，后续保护不影响所复用的通过回复；补验方法和源日志逐项保留。','', '6段保留集不再宣称未见：原样保留失败，没有换样本冲抵。']
(D/'SOURCE_VERSION_MAP.md').write_text('\n'.join(v),encoding='utf-8')
F=D/'firmware-build-evidence';F.mkdir(exist_ok=True)
for pattern in ['*host*.log','*host*.exit','firmware-build-*.log','firmware-build-*.exit']:
 for p in S.glob(pattern):shutil.copy2(p,F/p.name)
assert (S/'firmware-build-02.exit').read_text().strip()=='0'
app=ROOT/'build-experience-repair-20261009/xiaozhi.bin'
source=[p for p in (ROOT/'main').rglob('*') if p.is_file() and p.suffix in {'.cc','.cpp','.c','.h','.hpp','.txt','.cmake'}]
assert all(p.stat().st_mtime<=app.stat().st_mtime for p in source)
fw=json.loads((D/'firmware-20261013/SHA256.json').read_text())
for item in fw:assert hashlib.sha256((D/'firmware-20261013'/item['file']).read_bytes()).hexdigest()==item['sha256']
assert hashlib.sha256(app.read_bytes()).hexdigest()==next(r['sha256'] for r in fw if r['file']=='xiaozhi.bin')
frozen={'compiled_app_sha256':hashlib.sha256(app.read_bytes()).hexdigest(),'build_exit':0,'build_log_sha256':hashlib.sha256((S/'firmware-build-02.log').read_bytes()).hexdigest(),'source_hashes_at_delivery':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in source},'no_source_newer_than_compiled_app':True,'not_flashed':True,'host_cases':{'hello':10,'usb':7,'face':5,'tts':24,'ota_lock':9},'original_failure_logs_preserved':True}
(F/'firmware-source-artifact-manifest.json').write_text(json.dumps(frozen,indent=2),encoding='utf-8')
charges=json.loads((E/'budget-charges-export.json').read_text());unclosed=collections.Counter(r['kind'] for r in charges if r['metadata'] is None)
deployment=json.loads((E/'deployment-followup.json').read_text());stamp=datetime.datetime.fromtimestamp(deployment['completed_at'],datetime.timezone(datetime.timedelta(hours=8))).isoformat()
summary={'deployed_at_china':stamp,'business_evidence_origins':dict(counts),'budget':deployment['budget'],'unfinished_charge_metadata':dict(unclosed),'release':deployment['release'],'firmware':'compiled_not_flashed','hardware_accepted':False,'historical_data_restored':False}
(D/'DELIVERY_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
hashes={str(p.relative_to(D)).replace('\\','/'):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in D.rglob('*') if p.is_file() and p.name!='DELIVERY_SHA256.json'}
(D/'DELIVERY_SHA256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
