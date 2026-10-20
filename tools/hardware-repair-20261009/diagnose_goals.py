import bootstrap
from core.utils.tool_harness.runtime import Harness,literal_constraints,relative_requirements,live_read_request
from core.utils.recipient_resolver import extract_recipient_selector_from_text
for q in ['声音改成九成半吧','帮我把音量往上加十个点','帮我给我定一个晚上十点的闹钟']:
 print(q,Harness.write_targets(q),literal_constraints(q),relative_requirements(q),live_read_request(q),extract_recipient_selector_from_text(q))
