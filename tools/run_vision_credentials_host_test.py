#!/usr/bin/env python3
"""Build and run production vision_credentials.cc host lifecycle tests.

Exit codes:
  0 - compiled against production sources and runtime tests passed
  1 - compile or runtime failure
  2 - no host C++ compiler (NOT VERIFIED)
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"
OUT_DIR = ROOT / "build" / "host_tests"
OUT = OUT_DIR / "test_vision_credentials_host.exe"
SRC = ROOT / "tools" / "test_vision_credentials_host.cpp"
PROD = MAIN / "vision_credentials.cc"
STUB_LOG = OUT_DIR / "esp_log.h"

COMPILER_CANDIDATES = [
    "g++",
    "clang++",
    r"C:\msys64\mingw64\bin\g++.exe",
    r"C:\msys64\ucrt64\bin\g++.exe",
    str(ROOT / "build" / "host_mingw" / "llvm-mingw-20250613-ucrt-x86_64" / "bin" / "g++.exe"),
    str(ROOT / "build" / "host_mingw" / "mingw64" / "bin" / "g++.exe"),
]


def find_compiler() -> str | None:
    for cand in COMPILER_CANDIDATES:
        path = shutil.which(cand) if not Path(cand).is_absolute() else (cand if Path(cand).exists() else None)
        if path:
            return path
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if vswhere.exists():
        proc = subprocess.run(
            [str(vswhere), "-latest", "-requires",
             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            matches = glob.glob(
                str(Path(proc.stdout.strip()) / "VC" / "Tools" / "MSVC" / "*" /
                    "bin" / "Hostx64" / "x64" / "cl.exe")
            )
            if matches:
                return matches[-1]
    return None


def write_stub() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STUB_LOG.write_text(
        "#pragma once\n"
        "#include <cstdio>\n"
        "#define ESP_LOGI(tag, fmt, ...) ((void)std::fprintf(stderr, fmt \"\\n\", ##__VA_ARGS__))\n"
        "#define ESP_LOGW(tag, fmt, ...) ((void)std::fprintf(stderr, fmt \"\\n\", ##__VA_ARGS__))\n"
        "#define ESP_LOGE(tag, fmt, ...) ((void)std::fprintf(stderr, fmt \"\\n\", ##__VA_ARGS__))\n",
        encoding="utf-8",
    )


def main() -> int:
    compiler = find_compiler()
    if not compiler:
        print("No host C++ compiler; runtime tests NOT VERIFIED", flush=True)
        return 2
    write_stub()
    is_msvc = compiler.lower().endswith("cl.exe")
    if is_msvc:
        cmd = [
            compiler, "/nologo", "/EHsc", "/std:c++17", "/O2",
            f"/I{MAIN}", f"/I{OUT_DIR}",
            str(SRC), str(PROD), f"/Fe:{OUT}",
        ]
    else:
        cmd = [
            compiler, "-std=c++17", "-O1", "-pthread",
            f"-I{MAIN}", f"-I{OUT_DIR}",
            str(SRC), str(PROD), "-o", str(OUT),
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
