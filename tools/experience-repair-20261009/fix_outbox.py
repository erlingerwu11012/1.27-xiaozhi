from pathlib import Path
p=Path(__file__).parent/'candidate/core/utils/recent_memory.py'
s=p.read_text(encoding='utf-8').replace('from core.utils.person_material_outbox import outbox\n    outbox().suppress(actor,match)','from core.utils.person_material_outbox import material_outbox\n    material_outbox.suppress(actor,match)');p.write_text(s,encoding='utf-8')
