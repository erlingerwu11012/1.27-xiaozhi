from pathlib import Path
import json
S=Path('/root/prjs/tmp/hardware-followup-20261013');m=json.loads((S/'predeploy-backup02/manifest.json').read_text())
out={k:m[k] for k in ['created','restore_passed','restore_database','table_count','no_migration_required','existing_columns','sqlite_snapshots','rollback_jar_sha256','production_business_writes','model_calls']}
(S/'backup-restore-evidence.json').write_text(json.dumps(out,indent=2));print('restore_evidence_saved',out['restore_passed'],out['table_count'])
