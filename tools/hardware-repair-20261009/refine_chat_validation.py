from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'run_model.py';s=p.read_text(encoding='utf-8').replace("r'上周.{0,15}(?:停留|主要|只是|只).{0,10}标题'", "r'上周[^，,。；;]{0,15}(?:停留|主要|只是|只)[^，,。；;]{0,10}标题'");p.write_text(s,encoding='utf-8')
p=R/'work/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8').replace('不要为了接话改写用户事实；','不要为了接话改写用户事实；用户只是分享近况时，围绕话题自然回应，不主动提出记录、设提醒或安排计划，不以每次追问收尾；');p.write_text(s,encoding='utf-8')
