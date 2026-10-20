#!/usr/bin/env python3
"""Build/run production websocket_connection_gate.cc dispatch host tests."""
from __future__ import annotations

import glob
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"
OUT_DIR = ROOT / "build" / "host_tests"
OUT = OUT_DIR / "test_websocket_rx_gate_host.exe"
SRC = ROOT / "tools" / "test_websocket_rx_gate_host.cpp"
GATE_CC = MAIN / "protocols" / "websocket_connection_gate.cc"
VISION_CC = MAIN / "vision_credentials.cc"
CJSON_C = Path("/mnt/e/Espressif/frameworks/esp-idf-v5.5.4/components/json/cJSON/cJSON.c")
CJSON_INC = Path("/mnt/e/Espressif/frameworks/esp-idf-v5.5.4/components/json/cJSON")
if not CJSON_C.exists():
    CJSON_C = Path(r"E:\Espressif\frameworks\esp-idf-v5.5.4\components\json\cJSON\cJSON.c")
    CJSON_INC = Path(r"E:\Espressif\frameworks\esp-idf-v5.5.4\components\json\cJSON")

COMPILER_CANDIDATES = [
    "g++",
    "clang++",
    r"C:\msys64\mingw64\bin\g++.exe",
    str(ROOT / "build" / "host_mingw" / "llvm-mingw-20250613-ucrt-x86_64" / "bin" / "g++.exe"),
]


def find_compiler() -> str | None:
    for cand in COMPILER_CANDIDATES:
        path = shutil.which(cand) if not Path(cand).is_absolute() else (
            cand if Path(cand).exists() else None)
        if path:
            return path
    return None


def main() -> int:
    compiler = find_compiler()
    if not compiler:
        print("No host C++ compiler; runtime tests NOT VERIFIED", flush=True)
        return 2
    if not CJSON_C.exists():
        print(f"cJSON not found at {CJSON_C}; NOT VERIFIED", flush=True)
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "esp_log.h").write_text(
        "#pragma once\n#include <cstdio>\n"
        "#define ESP_LOGI(tag, fmt, ...) "
        "((void)std::fprintf(stderr, fmt \"\\n\", ##__VA_ARGS__))\n"
        "#define ESP_LOGW(tag, fmt, ...) "
        "((void)std::fprintf(stderr, fmt \"\\n\", ##__VA_ARGS__))\n"
        "#define ESP_LOGE(tag, fmt, ...) "
        "((void)std::fprintf(stderr, fmt \"\\n\", ##__VA_ARGS__))\n",
        encoding="utf-8",
    )
    cmd = [
        compiler, "-std=c++17", "-O1", "-pthread",
        f"-I{MAIN}", f"-I{MAIN / 'protocols'}", f"-I{OUT_DIR}", f"-I{CJSON_INC}",
        str(SRC), str(GATE_CC), str(VISION_CC), str(CJSON_C),
        "-o", str(OUT),
    ]
    print("COMPILE:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)
    print("RUN:", OUT, flush=True)
    subprocess.run([str(OUT)], check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"FAILED: {exc}", flush=True)
        raise SystemExit(1)
