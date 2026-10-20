$ErrorActionPreference='Stop'
$dest=Join-Path $PSScriptRoot 'evidence'
New-Item -ItemType Directory -Path $dest -Force | Out-Null
$remote='root@121.40.239.140:/root/prjs/tmp/hardware-repair-20261009/'
$files=@('resume-acceptance-summary.json','resume-usage-summary.json','resume-source-manifest.json','resume-source-only.tgz','resume-dialogues-only.md','resume-complete-dialogues.md','resume-final-results.jsonl','resume-final-freeze.json','resume-final-summary.json','resume-final-review.json','retained-failures-index.json','resume-holdout-audit.json','before-holdout-audit-resume-release-gate.json','before-holdout-audit-resume-acceptance-summary.json','resume-release-gate.json','live-deployed-config.json','live-model-route.json','memory-cleanup-applied.json','memory-cleanup-readback.json','memory-cleanup-restore-test.json','resume-regression-summary.json','http-api-results.json','firmware-host-results.json','photo-worker-host-results.json','supplement-results.json','resume-speech-regression.json','relative-claims-regression.json','shipping-state-regression.json','voice-backend-threshold.json','java-drift-preflight.json','python-drift-preflight.json','relative-review.json','short-memory-review.json','shipping-review.json','state-validation-review.json')
foreach ($name in $files) {
 & scp ($remote+$name) (Join-Path $dest $name)
 if ($LASTEXITCODE -ne 0) { throw "Failed collecting $name" }
}
foreach ($name in @('deployment-state.json','observation.json')) {
 & scp ('root@121.40.239.140:/root/prjs/releases/hardware-repair-20261009/'+$name) (Join-Path $dest $name)
 if ($LASTEXITCODE -ne 0) { throw "Failed collecting $name" }
}
$failed=Join-Path $dest 'retained-failed-runs'
New-Item -ItemType Directory -Path $failed -Force | Out-Null
foreach ($name in @('initial-final-incomplete-results.jsonl','resume-focus-results.jsonl','final-results.jsonl','resume-speech-results.jsonl','development-results.jsonl','resume-relative-failures-results.jsonl','resume-short-memory-failures-results.jsonl','resume-before-shipping-review-results.jsonl','resume-card-progress-failures-results.jsonl','resume-card-view-results.jsonl','resume-state-validation-failures-results.jsonl')) {
 & scp ($remote+$name) (Join-Path $failed $name)
 if ($LASTEXITCODE -ne 0) { throw "Failed collecting original $name" }
}
Write-Output 'Collected public-safe synthetic test evidence; no private configs or user memory backups copied.'
