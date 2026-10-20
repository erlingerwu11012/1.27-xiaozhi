from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'run_model.py';s=p.read_text(encoding='utf-8').replace("cli.add_argument('--focus',action='store_true');opt", "cli.add_argument('--focus',action='store_true');cli.add_argument('--speech-focus',action='store_true');opt")
s=s.replace(" assert not REPORT.exists()", " if opt.speech_focus:\n  CASES=[x for x in CASES if x['id'] in {'reg-19','reg-20','reg-53','reg-54','reg-102','reg-180','coverage-habit-learn'} or x.get('session') in {'chat0','chat1'}]\n assert not REPORT.exists()")
p.write_text(s,encoding='utf-8')
