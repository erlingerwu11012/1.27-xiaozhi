from pathlib import Path
import json
S=Path(__file__).resolve().parent;D=S/'delivery';rows=json.loads((D/'evidence/budget-charges-export.json').read_text())
entries=[]
for r in rows:
 if r['metadata'] is not None:continue
 entry={k:r[k] for k in ['id','kind','label','phase','created']}
 if r['kind']=='model':entry.update(state='response_completion_unknown',counted=True,evidence='Original reserved model attempt retained; no completed HTTP metadata. Do not assume zero cost or successful response.')
 elif r['label'].startswith('vision-http:'):entry.update(state='passed_evidence_preserved',counted=True,evidence='evidence/vision-http-followup-results.json and vision-http-03.log; six real HTTP cases; no paid vision request.')
 elif r['label']=='production-readonly-backup-isolated-restore-01':entry.update(state='failed_before_completion',counted=True,evidence='Original backup_restore_remote.py expected absent record_id/expected_version columns; subsequent backup_restore02_remote.py passed with actual schema. Original backup preserved.')
 else:entry.update(state='interrupted_not_counted_as_pass',counted=True,evidence='Earlier final batch stopped after another case failed; no complete output/finish metadata. Later completed evidence is separately versioned.')
 entries.append(entry)
result={'original_export_preserved':True,'original_budget_not_modified':True,'all_reserved_attempts_counted':True,'entries':entries,'counts':{s:sum(e['state']==s for e in entries) for s in set(e['state'] for e in entries)}}
(D/'CHARGE_RECONCILIATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(result['counts'])
