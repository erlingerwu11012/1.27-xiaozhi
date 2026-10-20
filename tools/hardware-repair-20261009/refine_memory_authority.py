from pathlib import Path
p=Path('tools/hardware-repair-20261009/work/core/utils/tool_harness/memory_policy.py');s=p.read_text(encoding='utf-8');needle="    # The question word can belong";insert="    if re.search(r'是不是|是否|(?:删|改|忘|更新|更正).{0,5}(?:过|了吗|了没|吗[？?]?$)',q) and not re.search(r'请|帮我|替我|能不能帮|把|将',q):return 'read'\n";s=s.replace(needle,insert+needle,1);p.write_text(s,encoding='utf-8')
