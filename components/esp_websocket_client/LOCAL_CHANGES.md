# Local WebSocket client

Based on the workspace's `espressif/esp_websocket_client` 1.7.0 snapshot
(upstream metadata commit `b385915ca011094238f5e8ebc45d539183b09cf2`).
Existing workspace changes are preserved. `main/idf_component.yml` uses
`override_path` so dependency refreshes cannot silently replace these fixes.
The Apache-2.0 license is included.

## Audio send timeout repair

- Paired with the project's `tcp_transport` component. The transport returns
  `ESP_TRANSPORT_WS_SEND_NOT_STARTED` only when the pre-header readiness poll
  times out. After a header write, any payload failure is normalized to `-1`.
- A complete text/binary message with no previous fragment written can return
  `ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED` (-2, socket not writable before the
  header) without an ERROR/DISCONNECTED event. TX lock timeouts return
  `ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT` (-3) for complete messages.
  Both mean "message not started" and are safe to drop as a single audio
  packet; diagnostics must keep the two classes distinct.
- A partial write, timeout after an earlier fragment, or transport error still
  aborts. The caller must never discard an unfinished frame/message and proceed.
- Error event structures are zero-initialized. Previously, non-TCP error events
  could expose uninitialized TLS/socket diagnostic fields.
- The receive task rechecks run/state after acquiring its lock following poll.
  A sender may have aborted while the poll was running outside that lock.
- Zero-length messages do not pass a null pointer to `memcpy`.

Tests: `python3 tools/run_ws_audio_send_host_test.py` with a native C++ compiler.
It extracts production transport/client/wrapper/protocol/queue functions and
runs them with injected I/O failures under ASan and UBSan, with both locking
configurations. It does not emulate behavior in a separate Python model.
