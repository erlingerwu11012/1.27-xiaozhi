from pathlib import Path
p=Path('tools/hardware-repair-20261009/release.py');s=p.read_text(encoding='utf-8');s=s.replace("'supplement-results.json','chat-fix-results.json'", "'supplement-results.json','chat-fix-results.json','resume-speech-regression.json'")
s=s.replace(" review=read(S/'resume-final-review.json');", " requirements['persona_equivalence']=read(S/'resume-persona-equivalence.json')['matched'] is True\n review=read(S/'resume-final-review.json');")
p.write_text(s,encoding='utf-8')
