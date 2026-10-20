from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text();s=s.replace('早|晨|上午|中午|下午|晚上|夜|凌晨|傍晚','早|晨|上午|中午|下午|晚上|今晚|今夜|夜|凌晨|傍晚');p.write_text(s,encoding='utf-8')
p=R/'budget.py';s=p.read_text(encoding='utf-8-sig').replace("'model':600","'model':900");p.write_text(s,encoding='utf-8')
