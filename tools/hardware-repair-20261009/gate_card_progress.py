from pathlib import Path
p=Path('tools/hardware-repair-20261009/release.py');s=p.read_text(encoding='utf-8').replace("'resume-speech-regression.json'", "'resume-speech-regression.json','card-progress-regression.json'");p.write_text(s,encoding='utf-8')
