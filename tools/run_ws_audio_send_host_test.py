#!/usr/bin/env python3
"""Compile actual production send functions with injected transport failures.

Requires a host C++ compiler (run in WSL on Windows if necessary). The harness
stubs hardware/RTOS calls, not the send policy. No copied Python behavior model.
"""
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def function(path, signature):
    source = (ROOT / path).read_text(encoding="utf-8")
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise SystemExit("No host C++ compiler; runtime tests NOT VERIFIED")
    source = (ROOT / "tools/test_ws_audio_send_host.cpp").read_text(encoding="utf-8")
    snippets = {
        "TRANSPORT": function("components/tcp_transport/transport_ws.c", "static int _ws_write("),
        "CLIENT": function("components/esp_websocket_client/esp_websocket_client.c", "static int esp_websocket_client_send_with_exact_opcode("),
        "FINALIZE": function("main/esp_network.h", "bool FinalizeSend("),
        "PROTOCOL": function("main/protocols/websocket_protocol.cc", "bool WebsocketProtocol::SendAudio("),
        "QUEUE": function("main/audio/audio_service.cc", "std::unique_ptr<AudioStreamPacket> AudioService::PopPacketFromSendQueue("),
    }
    for name, body in snippets.items():
        source = source.replace("// @" + name, body)
    constants = []
    for path, macro in [
        ("components/tcp_transport/include/esp_transport_ws.h", "ESP_TRANSPORT_WS_SEND_NOT_STARTED"),
        ("components/esp_websocket_client/include/esp_websocket_client.h", "ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED"),
        ("components/esp_websocket_client/include/esp_websocket_client.h", "ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT"),
    ]:
        constants.append(re.search(r"^#define " + macro + r" .*", (ROOT / path).read_text(), re.M)[0])
    source = source.replace("// @CONSTANTS", "\n".join(constants))
    out = ROOT / "build/ws_send_host"
    out.mkdir(parents=True, exist_ok=True)
    generated = out / "send_test.cpp"
    generated.write_text(source, encoding="utf-8")
    # Both library locking configurations must release their locks correctly.
    for separate_lock in (0, 1):
        binary = out / ("send_test_" + str(separate_lock))
        cmd = [compiler, "-std=c++17", "-g", "-O1", "-pthread",
               "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-omit-frame-pointer",
               str(generated), "-o", str(binary)]
        if separate_lock:
            cmd.append("-DCONFIG_ESP_WS_CLIENT_SEPARATE_TX_LOCK=1")
        subprocess.run(cmd, check=True)
        subprocess.run([str(binary)], check=True)
        print(f"PASS: production send/queue fault injection, separate_tx_lock={separate_lock}", flush=True)


if __name__ == "__main__":
    main()
