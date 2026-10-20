# TTS / Spine synchronization — 2026-10-13

Target: `ac:a7:04:fd:20:2c`. COM9 is the UART log port; COM10 is the native USB download port.

## Implemented

- Local PCM output owns the mouth animation. Network start, captions, LLM emotion and Home state do not start it.
- All server TTS packets carry a local-only generation; local sounds remain generation zero.
- Decode/output in-flight ownership and a 60 ms DMA tail are included in drain detection. A drained inter-sentence gap pauses the mouth after another 200 ms.
- Abort/reset/turn replacement/connection closure invalidate old animation ownership. The Spine empty-track operation restores the idle pose.
- The retired cloud `touch_prompt` behavior and its ASR prompt injection were removed. Current local gestures remain.

## Validation and release evidence

- `evidence/validation.json`: four successful suites, including the existing production-handler scenarios, PCM output/reset races, real nvhai skeleton poses, and ten server MCP/touch tests.
- `evidence/firmware-build.log`: final firmware compile/link/size check. Application size: `0x4acbc0`; partition: `0x4f0000`.
- `firmware/manifest.json`: exact application, ELF, source and rollback-image hashes.
- `firmware/flash-result.json` and `firmware/flash.log`: COM10 MAC/layout checks and verified app-only write.
- `evidence/server-deployment.json`: independent server release `/root/prjs/releases/tts-spine-sync-20261013`, PM2 ID 13. Previous release/PM2 ID 12 retained; database and nginx unchanged.
- `baseline/device-app-before.bin`: the full previous factory application partition; `baseline/device-partition-table.bin`: read-back layout. `baseline/working-tree-before.patch` and source copies preserve pre-existing local edits.

## Repeat checks

On Ubuntu/WSL, from the repository root:

```sh
python3 tools/tts-spine-sync-20261013/run_validation.py
```

Use `capture_serial.py --port COM9 --seconds 60` for a bounded UART capture without DTR/RTS reset.
Use the Python interpreter bundled with ESP-IDF for serial operations.

## Rollback

Server: stop PM2 ID 13, restart PM2 ID 12, check ports 8270/8273/8276, then `pm2 save`.

Firmware: enter download mode, verify the same MAC and partition table again, and write only the saved application image at `0x20000`. Do not write the partition table, NVS, assets, Spine or wallpaper partitions. Retain the recorded backup SHA256 to verify the image before any rollback.

## Hardware acceptance

The first app-only flash passed identity/layout/hash verification, but the user reported speech without visible mouth motion. This is a failed physical acceptance, not a pass. UART confirms PCM-driven track start and stop, including generation 4 at local 478859/478912/479143 ms (PCM/applied/frame submitted).

The real resource regression reproduced a second issue: idle owns the `zuiba1` slot's attachment and selects `zui2`, while talk_start omits an attachment timeline and expects the setup `zuiba1` attachment. Overlaying talk_start scales the wrong mouth artwork. The mouth-fix application prepares a missing setup-attachment key only for nvhai_builtin before any tracks start. Existing authored keys and asset bytes are preserved. Tests now require the talking attachment during playback and the idle attachment after stop. `firmware-mouthfix/` is an independent revision; the first package and rollback image are retained.

Basic physical playback acceptance confirmed by the user on 2026-10-13: the mouth opens/closes while speaking and stops automatically after speech. The user explicitly ended further testing. Reminder playback, double-tap/wake-word interruption, controlled inter-sentence gaps and gesture regressions are not claimed as physically verified.

`evidence/serial-20261013-193643.log` records multiple complete local PCM / talk_start / stop-and-drained cycles. For generation 1, first PCM/request/applied/frame submitted were at local 1086977/1086977/1087008/1087253 ms; stop request/applied/frame submitted were 1089863/1089992/1090144 ms. These are request/submission timestamps, not direct measurements of LCD completion or audible tail timing. The mouth-fix flash hash is `2f4eb991a2d617c92c89054e0e6aafae8e4c68b77f98d8104251d9d9548bcbe7`.

At the 19:36 server recheck, the filesystem had approximately 8 GB available and fresh dialogue TTS completed. No historical cleanup was performed by this task during that recheck.

## Deployment incident and recovery

The initial release copy followed the previous runtime's `models` symlink and created a 944,081,061-byte duplicate (19 model files). The root filesystem filled; MySQL could not write its binlog, billing transactions stalled, and the first hardware dialogue timed out before producing TTS.

`repair_release_links.py` verified every cloned model file against the original by size and SHA256, restored the original models link, and deleted only this release's duplicate. The original model files remain intact. The configuration symlink was also restored, retaining the copied config as a small rollback file. The deployment script now uses `symlinks=True`.

At the recovery check, MySQL had no active transactions or lock waits. Only about 27 MB of normal filesystem space remained, so historical-file cleanup is still a separate task requiring exact target selection. `evidence/server-link-repair.json` records the cleanup. The timed-out dialogue is not hardware acceptance evidence; a fresh dialogue is required.
