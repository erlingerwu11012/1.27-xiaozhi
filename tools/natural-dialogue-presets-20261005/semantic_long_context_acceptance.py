"""Replay actual long-context misses and controls; do not rewrite their records."""
import os,json
from pathlib import Path
root=Path(__file__).parent
data=json.loads((root/'complete-chat-semantic-full.json').read_text())
selected=[
 ('existing-playful',1,9,'unsupported_fact'),
 ('existing-playful',4,9,'unsupported_fact'),
 ('partner',2,9,'unsupported_fact'),
 ('playful',3,9,'unsupported_fact'),
 ('rational',4,9,'unsupported_fact'),
 ('humorous',4,7,'unsupported_fact'),
 ('natural',1,9,'unsolicited_advice'),
 ('natural',0,10,None),
 ('natural',0,8,None),
 ('humorous',2,7,None),
 ('existing-playful',3,10,None),
 ('natural',0,9,None),
 ('listener',3,9,None),
]
cases=[]
for persona,scenario,turn,expected in selected:
 entry=next(d for d in data['dialogues'] if d['persona']==persona and d['scenario']==scenario)
 record=entry['turns'][turn-1]
 cases.append(([t['user'] for t in entry['turns'][:turn]],record['assistant'],expected))
os.environ['JUDGE_REPORT']='complete-chat-judge-long-context'
source=(root/'semantic_checker_acceptance.py').read_text()
start=source.index('cases=[');end=source.index('\nchecker=',start)
source=source[:start]+'cases='+repr(cases)+'\n'+source[end:]
exec(compile(source,'<long-context-checker>', 'exec'))
