#!/usr/bin/env python3
"""Capture device logs without resetting or flashing the device."""
import argparse
from datetime import datetime
from pathlib import Path
import time
import serial

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM10')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--seconds', type=float, default=240)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('--seconds must be positive')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    port = serial.Serial(port=None, baudrate=args.baud, timeout=0.25)
    port.port = args.port
    port.dtr = False
    port.rts = False
    start = time.monotonic()
    try:
        port.open()
        with output.open('w', encoding='utf-8', buffering=1) as log:
            log.write('# Capture started: ' + datetime.now().isoformat() + '\n')
            log.write(f'# port={args.port} baud={args.baud} duration_s={args.seconds}\n')
            while time.monotonic() - start < args.seconds:
                data = port.readline()
                if data:
                    line = data.decode('utf-8', errors='replace')
                    log.write(line)
                    print(line, end='', flush=True)
    except KeyboardInterrupt:
        print('\nCapture stopped; received logs were saved.')
    finally:
        port.close()
    print('Saved:', output.resolve())

if __name__ == '__main__':
    main()
