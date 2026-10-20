from pathlib import Path
import tarfile,sys
s=Path('tools/experience-repair-20261009'); out=s/'evidence';out.mkdir(exist_ok=True)
with tarfile.open(s/(sys.argv[1] if len(sys.argv)>1 else 'delivery-evidence-draft.tgz')) as t:
 for m in t.getmembers():
  p=(out/m.name).resolve()
  assert p.is_relative_to(out.resolve()) and m.isfile(), m.name
 t.extractall(out)
print(len(list(out.iterdir())))
