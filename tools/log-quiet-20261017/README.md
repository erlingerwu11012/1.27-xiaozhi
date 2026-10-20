# Normal-use logging

The following verbose diagnostic output is disabled by default:

- `CONFIG_TASK_DIAGNOSTICS_PERIODIC`: every-15-second TASKPERF, TASKCPU,
  TASKHEAP, TASKCFG and full TASKLIST snapshots. Allocation failure monitoring
  remains active; explicitly requested diagnostic snapshots still work.
- `CONFIG_AUDIO_WAKE_DIAGNOSTICS`: every-second microphone/reference levels.
- Missing optional tasks are DEBUG messages, not WARN messages. Missing
  required tasks still produce warnings when a diagnostic check is requested.

AFE fetching waits up to 100 ms instead of 20 ms (a 512-sample input frame at
16 kHz takes 32 ms). A stopped wake detector does not fetch an unfed AFE.
AFE warnings are not globally suppressed; persistent feed problems remain
visible. Wake threshold, command, microphone gain and server settings do not
change.

Startup, state transitions, wake detections, connection/authentication errors,
audio queue pressure and allocation failures remain visible on the USB console.
Temporary detailed diagnostics can be restored with the two configuration
options above.

The production-method host regression includes stopped-detector resume and
stale-frame isolation under ASan/UBSan. Hardware acceptance requires flashing
the new app and checking idle logs, wake, dialogue and speaking interruption.
