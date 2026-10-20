"""Read-only loopback metadata capture. Never persist bodies or auth headers."""
import json, os, select, socket, struct, subprocess, time

p = subprocess.Popen(['tcpdump', '-i', 'lo', '-U', '-n', '-s', '1024', '-w', '-',
                      'tcp dst port 8006'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 85
buf = b''
endian = None
seen = set()
try:
    while time.monotonic() < deadline:
        if not select.select([p.stdout], [], [], 1)[0]:
            continue
        block = os.read(p.stdout.fileno(), 65536)
        if not block:
            break
        buf += block
        if endian is None:
            if len(buf) < 24:
                continue
            endian = '<' if buf[:4] == b'\xd4\xc3\xb2\xa1' else '>'
            buf = buf[24:]
        while len(buf) >= 16:
            seconds, micros, size, _ = struct.unpack(endian + 'IIII', buf[:16])
            if len(buf) < 16 + size:
                break
            frame, buf = buf[16:16+size], buf[16+size:]
            ip = frame[14:]
            if len(ip) < 40 or ip[0] >> 4 != 4 or ip[9] != 6:
                continue
            tcp = ip[(ip[0] & 15)*4:]
            sport, dport = struct.unpack('!HH', tcp[:4])
            payload = tcp[(tcp[12] >> 4)*4:]
            if not payload.startswith((b'POST ', b'GET ')):
                continue
            headers = payload.split(b'\r\n\r\n', 1)[0].decode('ascii', errors='replace')
            lines = headers.split('\r\n')
            if '/api/v1/device/send' not in lines[0]:
                continue
            key = (sport, lines[0])
            if key in seen:
                continue
            seen.add(key)
            agent = next((line.split(':', 1)[1].strip() for line in lines
                          if line.lower().startswith('user-agent:')), '')
            auth_present = any(line.lower().startswith('authorization:') for line in lines)
            sockets = subprocess.run(['ss', '-tnp', 'sport = :'+str(sport)],
                                     capture_output=True, text=True).stdout.strip()
            print(json.dumps({'at': time.strftime('%H:%M:%S', time.localtime(seconds)),
                              'request': lines[0], 'client_port': sport, 'user_agent': agent,
                              'authorization_present': auth_present,
                              'socket_owner': sockets}, ensure_ascii=False), flush=True)
finally:
    p.terminate()
    p.wait(timeout=5)
print(json.dumps({'matched_requests': len(seen), 'captured_auth_values': False,
                  'captured_bodies': False}), flush=True)
