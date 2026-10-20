# USB flash-port runtime logs

The ESP-BOX-3 runtime logger uses the native USB Serial/JTAG console instead of
UART2/GPIO14. UVC support remains compiled into the firmware.

Before booting, move the physical switch to the desired interface:

- **USB/PC:** connect a USB data cable to an awake computer, then reboot. The
  board detects host SOF packets before starting OTG Host and reserves the
  shared PHY for the console. Open the flash port (currently COM11).
- **UVC:** move the switch to the camera interface, then reboot. With no PC
  detected during the boot window, the existing camera Host path runs.

This is a boot-time selection, not live USB role switching. Power-only cables
and power banks do not count as a connected PC. Windows owns COM numbering.

Capture logs without toggling the boot/reset control lines:

```powershell
& 'E:/Espressif/python_env/idf5.5_py3.11_env/Scripts/python.exe' tools/usb-console-20261017/capture_console.py --port COM11 --seconds 60
```

The raw UTF-8 output is saved as `runtime-console.log`. Its compact result is
saved as `console-result.json`. Backups, firmware images and raw logs are
ignored by Git because device settings may contain credentials.

`flash-result.json` records the app-only flash and protected partition checks.
`firmware-build.log` contains the full build output.

Verified on ac:a7:04:fd:20:5c / COM11: app-only flash hash matched; partition
table, NVS, PHY and userdata readbacks were unchanged before reboot. The USB
console boot message and microphone diagnostics were captured. A subsequent
55-second capture without reset commands received 106830 bytes, with no port
errors, reboot markers or crash traces; device uptime increased from 73620 ms
to 128500 ms. UVC mode remains compiled in but has not been tested after this
change. Frequent AFE empty-buffer warnings are a separate pending issue.
