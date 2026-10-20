import json, socket, sys
path='/root/prjs/tmp/natural-dialogue-20261003/probe.sock'
payload=sys.argv[1] if sys.argv[1].startswith('{') else json.dumps({'op':sys.argv[1]})
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
    sock.settimeout(80);sock.connect(path);sock.sendall((payload+'\n').encode())
    chunks=[]
    while True:
        part=sock.recv(65536)
        if not part:break
        chunks.append(part)
        if b'\n' in part:break
print(b''.join(chunks).decode().strip())
