"""Capture flash-port logs without toggling DTR/RTS or resetting the device."""
import argparse
import json
from pathlib import Path
import sys
import time

import serial
from serial.tools import list_ports


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default='COM11')
    parser.add_argument('--seconds', type=float, default=35)
    parser.add_argument('--reset', action='store_true', help='Explicitly reboot once while capturing startup')
    parser.add_argument('--output-dir', type=Path, help='Directory for this capture')
    args = parser.parse_args()
    directory = args.output_dir.resolve() if args.output_dir else Path(__file__).resolve().parent
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.seconds
    captured = bytearray()
    errors = []
    reset_pending = args.reset
    while time.monotonic() < deadline:
        if args.port not in {p.device for p in list_ports.comports()}:
            time.sleep(0.2)
            continue
        stream = serial.Serial(port=None, baudrate=115200, timeout=0.2)
        stream.dtr = False
        stream.rts = False
        stream.port = args.port
        try:
            stream.open()
            if reset_pending:
                from esptool.reset import HardReset
                reset_pending = False
                stream.dtr = False
                HardReset(stream, uses_usb=True).reset()
            while time.monotonic() < deadline:
                captured.extend(stream.read(max(1, stream.in_waiting)))
        except (serial.SerialException, OSError) as error:
            errors.append(type(error).__name__)
            time.sleep(0.2)
        finally:
            stream.close()
    (directory / 'runtime-console.log').write_bytes(captured)
    decoded = captured.decode('utf-8', errors='replace')
    indicators = ['USB mode=console', '[CUSTOM_WAKE]', '[AUDIO_WAKE_DIAG]',
                  'Custom wake word detected',
                  'STATE:', 'Failed to initialize wake word', 'Guru Meditation',
                  'panic', 'http_ok', '[WS_AUTH]']
    safe_lines = [line for line in decoded.splitlines()
                  if any(item in line for item in indicators)
                  and not any(secret in line.lower() for secret in
                              ['authorization', 'auth_key', 'pairing_secret', 'token='])]
    result = {'port': args.port, 'bytes': len(captured), 'errors': errors,
              'usb_console_mode_seen': 'USB mode=console' in decoded,
              'wake_initialization_seen': '[CUSTOM_WAKE] model=' in decoded,
              'wake_levels_seen': '[AUDIO_WAKE_DIAG]' in decoded}
    (directory / 'console-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    for line in safe_lines[-40:]:
        print(line)


if __name__ == '__main__':
    main()
