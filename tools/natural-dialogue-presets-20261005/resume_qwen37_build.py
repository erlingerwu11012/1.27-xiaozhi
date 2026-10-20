from pathlib import Path
import shutil
p=Path('/root/prjs/tmp/natural-dialogue-presets-20261005/prepare_qwen37_release_20261007.py')
s=p.read_text()
shutil.copytree(p.parent/'gateway-candidate/web/build',Path('/root/prjs/tmp/qwen37-official-release-20261007/gateway/web/build'),dirs_exist_ok=True)
prefix=s[:s.index('for src,dst')]
helpers=s[s.index('def run('):s.index("run(['/usr/local/go/bin/gofmt'")]
suffix=s[s.index("run(['/usr/local/go/bin/go','build'"):]
exec(prefix+"manifest=json.loads((ROOT/'source-manifest.json').read_text())\npack=json.loads((OUT/'qwen-paired-tool-pack-20261006.json').read_text())\n"+helpers+suffix)
