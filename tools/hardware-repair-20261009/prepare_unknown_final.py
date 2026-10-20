from pathlib import Path
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix)
 if p.exists():p.rename(S/('resume-before-unknown-guard-'+suffix))
print('preserved partial run; unknown memory claim guard changed, repeat final source validation')
