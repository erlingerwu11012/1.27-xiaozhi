from pathlib import Path
import tarfile,json,ast
S=Path('tools/experience-repair-20261009');out=S/'analysis-source';out.mkdir(exist_ok=True)
with tarfile.open(S/'evidence/candidate-changes.tgz') as t:
 for m in t.getmembers():
  assert (out/m.name).resolve().is_relative_to(out.resolve()) and m.isfile()
 t.extractall(out)
R=Path(json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'))['output']);catalog=[]
for l in (R/'server-0.log').read_text(encoding='utf-8').splitlines():
 if '当前支持的函数列表:' in l:catalog=ast.literal_eval(l.split('当前支持的函数列表:',1)[1].strip())
covered=json.loads((S/'evidence/tool-coverage.json').read_text(encoding='utf-8'));print(json.dumps({'live_catalog_count':len(catalog),'final_test_tool_count':len(covered),'live_not_tested':sorted(set(catalog)-set(covered)),'tested_not_live':sorted(set(covered)-set(catalog))},ensure_ascii=False))
