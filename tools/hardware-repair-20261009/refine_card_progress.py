from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');s=s.replace("r'查|看|确认|多少|多大|几档|什么|啥|最高档|最亮|最低档|最暗|还有|有没有'", "r'查|看|确认|多少|多大|几档|什么|啥|最高档|最亮|最低档|最暗|还有|有没有|是不是|是否|还在|关没关|状态'")
s=s.replace("        if not updated and re.search(r'大半|大部分|(?:全部|全都|都)(?:写好|写完|完成)|100[%％]',reply) and not re.search(r'还没|尚未|不是|未完成',reply):return source", "        if not updated and re.search(r'大半|大部分',reply) and not re.search(r'(?:不是|并非).{0,4}(?:大半|大部分)',reply):return source\n        if not updated and re.search(r'(?:全部|全都|都)(?:写好|写完|完成)|100[%％]',reply) and not re.search(r'还没|尚未|不是|未完成',reply):return source")
p.write_text(s,encoding='utf-8')
p=R/'run_model.py';s=p.read_text(encoding='utf-8');s=s.replace("or x.get('session') in {'chat0','chat1'}]", "or x.get('session') in {'chat0','chat1','fresh-card-1'}]") # speech focus and ordinary focus remain finite
p.write_text(s,encoding='utf-8')
