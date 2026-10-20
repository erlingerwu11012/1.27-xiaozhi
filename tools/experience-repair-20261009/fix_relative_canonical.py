from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
s=s.replace("    for clause in re.split('[，,；;。]',content_text(query)):\n", "    full=content_text(query)\n    for clause in re.split('[，,；;。]',full):\n        units=re.search(r'(?:往|向)?(上|下)(?:调|降|升|减|加)?([一二两三四五\\d]+)档',clause)\n        if units and re.search('屏幕|亮度',full):\n            count=cn_num_to_int(units[2])\n            if count:result['self_screen_set_brightness']=count if units[1]=='上' else -count\n            continue\n")
needle="                    if s.tool in adjustments and (s.relative!=adjustments[s.tool] or s.extreme is not None):"
replacement="""                    if s.relative is not None or s.extreme is not None:
                        # The executor computes this value from a verified status.
                        # Model-supplied absolute values/references are never used.
                        s.arguments={}
                    if s.tool=='self_screen_set_brightness' and s.relative is not None:
                        from .domains import bounds
                        if bounds(s.tool,tools[s.tool])==(1,5) and abs(s.relative)==10:
                            s.relative=1 if s.relative>0 else -1
                    if s.tool in adjustments and s.tool=='self_screen_set_brightness':
                        from .domains import bounds
                        if bounds(s.tool,tools[s.tool])==(1,5) and abs(adjustments[s.tool])==10:
                            adjustments[s.tool]=1 if adjustments[s.tool]>0 else -1
                    if s.tool in adjustments and (s.relative!=adjustments[s.tool] or s.extreme is not None):"""
assert needle in s;s=s.replace(needle,replacement);p.write_text(s,encoding='utf-8')
