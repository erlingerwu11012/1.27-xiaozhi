"""Run on the SSH server. Copy source only into a private mock candidate."""
from pathlib import Path
import shutil

ROOT = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
RELEASE = Path('/root/prjs/tmp/remove-llm-rewrite-20261003')
CANDIDATE = RELEASE / 'candidate'
CANDIDATE.mkdir(parents=True, exist_ok=True)
for name in ('core', 'config', 'plugins_func', 'test'):
    for p in (ROOT / name).rglob('*'):
        if p.is_file() and p.suffix in ('.py', '.txt', '.j2', '.jinja2') and '__pycache__' not in p.parts:
            dest = CANDIDATE / p.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
for p in ROOT.glob('*.txt'):
    shutil.copy2(p, CANDIDATE / p.name)
for p in (RELEASE / 'delivery').rglob('*.py'):
    dest = CANDIDATE / p.relative_to(RELEASE / 'delivery')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
(CANDIDATE / 'data').mkdir(exist_ok=True)
safe_config = 'read_config_from_api: false\nlog:\n  log_dir: tmp\n  log_level: ERROR\nselected_module: {}\n'
(CANDIDATE / 'config.yaml').write_text(safe_config)
(CANDIDATE / 'data/.config.yaml').write_text('{}\n')
print('candidate prepared; no production YAML, data or credentials copied')
