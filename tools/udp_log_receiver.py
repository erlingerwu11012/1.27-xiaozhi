"""
ESP32 UDP 日志接收器
用法：python udp_log_receiver.py
设备 WiFi 连上后，日志会自动广播到局域网 UDP 54321 端口
"""
import socket
import datetime
import sys

PORT = 12345

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("0.0.0.0", PORT))
    except PermissionError:
        # Windows 有时对 UDP 广播绑定有限制，尝试绑定到具体本机 IP
        import subprocess, re
        result = subprocess.run(["ipconfig"], capture_output=True, text=True, encoding="gbk")
        ips = re.findall(r'IPv4.*?:\s*([\d.]+)', result.stdout)
        local_ip = next((ip for ip in ips if not ip.startswith("169.")), None)
        if not local_ip:
            print(f"[错误] 无法绑定端口 {PORT}，且找不到本机 IP")
            sys.exit(1)
        print(f"[提示] 广播绑定失败，改用本机 IP {local_ip} 接收")
        sock.bind((local_ip, PORT))
    print(f"[UDP Log Receiver] 监听 UDP 端口 {PORT}，等待设备日志...")
    print(f"[UDP Log Receiver] 按 Ctrl+C 退出\n")

    log_file = f"esp32_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        try:
            while True:
                data, addr = sock.recvfrom(1024)
                msg = data.decode("utf-8", errors="replace").rstrip("\n")
                ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                line = f"[{ts}] {msg}"
                print(line, flush=True)
                f.write(line + "\n")
                f.flush()
        except KeyboardInterrupt:
            print(f"\n[UDP Log Receiver] 已停止，日志保存到 {log_file}")

if __name__ == "__main__":
    main()
