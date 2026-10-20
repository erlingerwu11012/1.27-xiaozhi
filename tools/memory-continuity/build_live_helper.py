from pathlib import Path
here=Path(__file__).resolve().parent
source=(here.parent/'context-memory-200k/seed_member_fact_20260930.py').read_text(encoding='utf-8').split('\nfact = ')[0]
source=source.replace('mode = sys.argv[1]','mode = "continuity"').replace("root = Path('/root/prjs/tmp/member-memory-test-20260930')","root = Path('/root/prjs/tmp/memory-continuity-release-20260930')")
source=source.replace("'http://127.0.0.1:3011/bailian/api/v2/apps/memory/'","'https://api.realecho.cn/bailian/api/v2/apps/memory/'")
(here/'live_auth.py').write_text(source,encoding='utf-8')
