"""Read-only, timestamped COM11 and device-filtered server capture. No reset."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import serial

REMOTE = r'''
import datetime, re, time
from pathlib import Path
p = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/tmp/server.log')
deadline = time.monotonic() + 300
ids = set()
with p.open(errors='replace') as f:
    f.seek(0, 2)
    print('SERVER_READY ' + datetime.datetime.now(datetime.timezone.utc).isoformat(), flush=True)
    while time.monotonic() < deadline:
        line = f.readline()
        if not line:
            time.sleep(.15)
            continue
        if any(s in line.lower() for s in ['authorization', 'auth_key', 'pairing_secret', 'api_key', '获取差异化配置', 'token=']):
            continue
        target = 'ac:a7:04:fd:20:5c' in line.lower() or 'aca704fd205c' in line.lower()
        if target:
            ids.update(re.findall(r'correlation_id=([a-zA-Z0-9-]+)', line))
        if target or any(s in line for s in ids):
            print(line.rstrip(), flush=True)
'''


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    out = Path(__file__).parent / ('live-' + stamp)
    out.mkdir()
    lock = threading.Lock()
    counts = {'firmware': 0, 'server': 0}
    errors = []
    logs = {name: (out / (name + '.log')).open('w', encoding='utf-8') for name in counts}

    def emit(source, line, show=True):
        if any(s in line.lower() for s in ['authorization', 'auth_key', 'pairing_secret', 'token=']):
            return
        at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')
        with lock:
            counts[source] += 1
            logs[source].write(at + ' ' + line + '\n')
            logs[source].flush()
            if show:
                print('[' + source + '] ' + at + ' ' + line, flush=True)

    stream = serial.Serial(port=None, baudrate=115200, timeout=.2)
    stream.dtr = False
    stream.rts = False
    stream.port = 'COM11'
    stream.open()
    proc = subprocess.Popen(
        ['C:/Windows/System32/OpenSSH/ssh.exe', '-o', 'BatchMode=yes',
         '-o', 'ConnectTimeout=10', 'root@121.40.239.140', 'python3 -u -'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding='utf-8', errors='replace')
    proc.stdin.write(REMOTE)
    proc.stdin.close()

    def server_reader():
        for line in proc.stdout:
            emit('server', line.rstrip())

    def error_reader():
        for line in proc.stderr:
            with lock:
                errors.append(line.strip())
            print('SSH: ' + line.strip(), flush=True)

    workers = [threading.Thread(target=fn, daemon=True) for fn in (server_reader, error_reader)]
    for worker in workers:
        worker.start()
    print('FIRMWARE_READY COM11 no_reset output=' + str(out.resolve()), flush=True)
    deadline = time.monotonic() + 300
    pending = bytearray()
    try:
        while time.monotonic() < deadline:
            pending.extend(stream.read(max(1, stream.in_waiting)))
            while b'\n' in pending:
                raw, _, pending = pending.partition(b'\n')
                line = raw.decode('utf-8', errors='replace').rstrip('\r')
                show = any(s in line for s in ['STATE:', '>>', '<<', '[WS_', 'MCP:', 'Custom wake word detected',
                                               'CUSTOM_WAKE', 'transport_base', 'websocket_client', ' E (',
                                               'Guru Meditation', 'panic', 'rst:', 'TTS_LOCAL', 'Alert'])
                emit('firmware', line, show)
    finally:
        stream.close()
        if pending:
            emit('firmware', pending.decode('utf-8', errors='replace'))
        if proc.poll() is None:
            proc.terminate()
        for worker in workers:
            worker.join(timeout=2)
        for log in logs.values():
            log.close()
        result = {'duration_seconds': 300, 'counts': counts, 'errors': errors, 'server_exit': proc.poll()}
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
