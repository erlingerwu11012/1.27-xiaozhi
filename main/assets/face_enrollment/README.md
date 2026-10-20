# Guided face-enrollment local prompts

Place the product-approved prompt recordings in this directory as `.ogg`
files containing **Ogg-container Opus**.  Do not use raw `.opus` streams.

Recordings are named after their exact `guidance_code` or local resource key
(for example `CAPTURE_LEFT.ogg`, `DRAFT_READY_FRONT_ONLY.ogg`).  Matching
subtitle and embedded byte view are defined in
`main/face_enrollment_prompt_catalog.cc`; the second field is the generated
Ogg byte `std::string_view`, not a runtime filename.

`FaceEnrollmentPromptCatalog::Present()` sends that view to
`Application::PlaySound`, and the state machine waits for
`AudioService::IsPlaybackDrained()` before it begins the next capture.  The
service must continue to return only `guidance_code`; it must not provide TTS
prose for this flow.

## Product WAV → Ogg (2026-09-19)

Fourteen prompts were replaced from confirmed WAV sources:

- Source directory:
  `docs/server-handoff-front-only-20260919/正式提示音-WAV-成品`
- Model / voice: `qwen-audio-3.0-tts-plus` / `longanlingxi`
- Encode: Ogg + libopus, mono, OpusHead input rate 16000, 16 kb/s VBR,
  `application=voip`, `frame_duration=60` (matches `AudioService::PlaySound`)

Replaced files:

`MOVE_USER_LEFT`, `MOVE_USER_RIGHT`, `DRAFT_READY_FRONT_ONLY`, `NO_FACE`,
`MOVE_UP`, `MOVE_DOWN`, `MOVE_CLOSER`, `MOVE_BACK`, `FACE_FORWARD`,
`TOO_DARK`, `MULTIPLE_FACES`, `HOLD_STILL`, `RECAPTURE_FRONT`, `POSE_FAILED`

`DRAFT_READY_FRONT_ONLY` remains a **local resource key** only; it is not a
server network guidance code.

## Intentionally unchanged

- `DRAFT_READY.ogg` — three-pose completion (“三张照片都拍好了…”)
- `MOVE_SCREEN_LEFT.ogg` / `MOVE_SCREEN_RIGHT.ogg` — screen-relative copy
- `CAPTURE_LEFT` / `CAPTURE_RIGHT` / `RECAPTURE_LEFT` / `RECAPTURE_RIGHT`
- Other catalog entries not listed above (`START`, `ALIGN_READY`, …)

Device playback of the new recordings still needs a flash + on-device listen
pass; a successful firmware build alone is not a product audio acceptance.
