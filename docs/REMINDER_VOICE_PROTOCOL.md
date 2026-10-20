# Reminder Voice Protocol

This document defines the optional cloud contract used by the ESP-BOX-3
reminder coordinator. Reminder state, time, priority, actions and permissions
remain device-authoritative. Cloud output can only provide constrained scripts
and matching audio assets.

## Device request

The firmware sends a normal protocol text message when a normal or high
priority reminder instance is created:

```json
{
  "type": "reminder_voice_request",
  "instance_id": "note:7:1785686400",
  "voice_revision": 1,
  "source_type": "note",
  "title": "带钥匙",
  "detail": "一次性提醒",
  "privacy_safe_text": "有一条提醒等你处理",
  "constraints": "one_fact_only;one_sentence;no_invented_people_or_consequences;no_blame_no_anxiety;state_and_actions_are_device_authoritative"
}
```

The cloud must treat every request independently. It must not infer completion,
urgency, people or consequences. Generated pre-alert and repeat scripts must
contain at most one sentence and one item.

## Cloud asset response

The cloud may return one message per phase:

```json
{
  "type": "reminder_voice_asset",
  "instance_id": "note:7:1785686400",
  "voice_revision": 1,
  "phase": "due",
  "script": "提醒你带钥匙。",
  "url": "https://cdn.example.com/reminders/abc.ogg",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "format": "ogg_opus",
  "bytes": 14200
}
```

Allowed phases are `pre_alert`, `due`, `repeat`, `completion`, `snooze`,
`skip` and `privacy_safe`.

Validation performed by firmware:

- URL must use HTTPS and be at most 512 bytes.
- SHA-256 must be exactly 64 lowercase hexadecimal characters.
- Format must be `ogg_opus`.
- Declared and HTTP `Content-Length` must match.
- Asset size must be 1–16384 bytes.
- Downloaded SHA-256 must match before the temporary file is committed.
- The instance must still exist and remain active.
- Response `voice_revision` must equal the current
  `ReminderInstance.voice_revision`
  exactly. Both older and future revisions are rejected before download,
  checked again before the temporary file is committed, checked when metadata
  is attached, and checked again before playback.

Cloud generation is asynchronous: a request may become stale while the cloud
is generating or while the device is downloading. The cloud may drop stale
work if it knows a newer voice revision, but correctness does not depend on that
optimization. The device safely ignores every late response whose
`instance_id + voice_revision` no longer exactly matches an active instance.

`ReminderInstance.revision` is intentionally not part of this protocol. It is
the card/action optimistic-concurrency version and may advance on show, hide,
preemption, recovery or other visual state transitions. `voice_revision` is
the semantic version of title, detail, privacy-safe text and voice context.
Visual transitions never advance `voice_revision` or invalidate matching
pre-generated audio. A real semantic change advances both versions, removes
the old voice assets and issues one request for the new voice revision.

The device requests scripts immediately after creating an instance. On card
presentation it retries only when the required phase is absent and the last
request is for another voice revision or is at least 60 seconds old. Partial
phase responses are valid; a missing phase always falls back locally without
waiting for the network.

Only one download is accepted at a time. A busy downloader rejects additional
responses; the cloud may retry while the instance remains active.

## Cache and fallback

Validated assets are stored in the existing `userdata` SPIFFS partition. The
file component is `r<25 lowercase hex>.ogg`, where the digest input is the
length-unambiguous sequence `instance_id`, `voice_revision`, `phase` and the
declared audio SHA-256. This keeps the component within the configured
32-byte SPIFFS name limit while making different phases and contents distinct.

At most two audio files are retained globally. Normal-priority assets are
evicted before high-priority assets; eviction removes both metadata and the
unreferenced file. Each instance persists at most two current-voice-revision
asset records. On load, legacy `/userdata/rv*.ogg`, metadata with a legacy or
unexpected path, and unreferenced new-format cache files are removed. Old
single-file-per-instance cache names are never playable as phase assets.

Every semantic voice revision change invalidates its older asset metadata and
removes unreferenced old files. Card revision changes do not. Playback requires
exact voice revision and phase equality; rejection never blocks the reminder
state machine, card rendering, or built-in sound.

Reminder state uses a 32 KiB atomic JSON store budget. Persistence always keeps
all active reminder core fields before optional data. Voice metadata is limited
to two assets per instance and ranked as follows: current voice revision only,
cached before uncached, then `due`, `privacy_safe`, current snooze/repeat and
pre-alert phases, with completion/skip feedback last. If the budget is still
exceeded, uncached voice metadata is removed, then all voice metadata, then
old terminal reminder history. Active reminder core state is never pruned; an
oversized core or filesystem write failure is logged and leaves the store
dirty for retry rather than claiming persistence succeeded. Firmware can read
the previous 64 KiB legacy format once and rewrites it in the bounded compact
format. On parse/read failure it attempts the atomic backup.

At attention time the firmware first attempts to play a cached asset matching
the instance and phase. If no valid asset is available, it immediately uses a
built-in sound:

- high priority and alarms: built-in attention sound;
- normal priority: built-in soft popup sound;
- completion/snooze/skip feedback: built-in success sound.

Card presentation and state transitions never wait for network or cloud audio.
The legacy free-form `[ALARM]`, `[NOTE]` and `[HABIT]` chat injection is not
used by the reminder coordinator.

## Error behavior

Malformed messages are rejected locally and logged. Download, size, hash,
storage or revision failures leave the reminder unchanged and use local audio.
There is no cloud command in this protocol that can complete, skip, snooze or
dismiss a reminder; actions must use the authenticated MCP reminder tools.
