#!/usr/bin/env python3
"""Build and run host tests for production main_ws_open::RunUnitTests().

Exit codes:
  0 - static checks pass AND host runtime tests executed and passed
  1 - static/runtime failure
  2 - static checks pass but no host C++ compiler available (NOT VERIFIED)
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"
HOST_CPP = ROOT / "tools" / "test_main_ws_open_arbiter_host.cpp"
ARB_CC = MAIN / "main_ws_open_arbiter.cc"
POLICY_CC = MAIN / "main_ws_submit_policy.cc"
ARB_H = MAIN / "main_ws_open_arbiter.h"
POLICY_H = MAIN / "main_ws_submit_policy.h"
APP_CC = MAIN / "application.cc"
OUT = ROOT / "build" / "test_main_ws_open_arbiter_host.exe"

VSWHERE_PATHS = [
    r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe",
    r"C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe",
]

COMPILER_CANDIDATES = [
    "g++",
    "clang++",
    r"C:\msys64\mingw64\bin\g++.exe",
    r"C:\msys64\ucrt64\bin\g++.exe",
    r"C:\MinGW\bin\g++.exe",
]


class CompilerInfo:
    def __init__(self, kind: str, executable: str, extra_args: list[str] | None = None):
        self.kind = kind
        self.executable = executable
        self.extra_args = extra_args or []


def find_msvc_cl() -> CompilerInfo | None:
    for vswhere in VSWHERE_PATHS:
        if not Path(vswhere).exists():
            continue
        proc = subprocess.run(
            [
                vswhere,
                "-latest",
                "-requires",
                "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property",
                "installationPath",
            ],
            capture_output=True,
            text=True,
        )
        install = proc.stdout.strip()
        if proc.returncode != 0 or not install:
            continue
        matches = glob.glob(
            str(Path(install) / "VC" / "Tools" / "MSVC" / "*" / "bin" / "Hostx64" / "x64" / "cl.exe")
        )
        if not matches:
            continue
        cl_path = sorted(matches)[-1]
        return CompilerInfo(
            "msvc",
            cl_path,
            ["/EHsc", "/std:c++17", "/nologo", f"/Fe:{OUT}"],
        )
    return None


def find_host_compiler() -> CompilerInfo | None:
    for candidate in COMPILER_CANDIDATES:
        path = shutil.which(candidate) if os.path.sep not in candidate else candidate
        if path and Path(path).exists():
            return CompilerInfo("gnu", path)
    return find_msvc_cl()


def build_and_run_host_test(compiler: CompilerInfo) -> tuple[int, str]:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()

    if compiler.kind == "msvc":
        cmd = [
            compiler.executable,
            *compiler.extra_args,
            f"/I{MAIN}",
            str(HOST_CPP),
            str(ARB_CC),
            str(POLICY_CC),
        ]
    else:
        cmd = [
            compiler.executable,
            "-std=c++17",
            f"-I{MAIN}",
            str(HOST_CPP),
            str(ARB_CC),
            str(POLICY_CC),
            "-o",
            str(OUT),
        ]

    compile_proc = subprocess.run(cmd, capture_output=True, text=True)
    if compile_proc.returncode != 0:
        output = compile_proc.stdout + compile_proc.stderr
        raise RuntimeError(f"host compile failed ({compiler.kind}):\n{output}")

    run_proc = subprocess.run([str(OUT)], capture_output=True, text=True)
    return run_proc.returncode, run_proc.stdout + run_proc.stderr


class StaticArbiterTests(unittest.TestCase):
    def test_production_run_unit_tests_export(self):
        text = ARB_CC.read_text(encoding="utf-8", errors="replace")
        header = ARB_H.read_text(encoding="utf-8", errors="replace")
        policy_cc = POLICY_CC.read_text(encoding="utf-8", errors="replace")
        policy_h = POLICY_H.read_text(encoding="utf-8", errors="replace")
        self.assertIn("bool RunUnitTests()", header)
        self.assertIn("bool RunUnitTests()", text)
        self.assertIn("bool RunUnitTests()", policy_h)
        self.assertIn("bool RunUnitTests()", policy_cc)
        self.assertIn("ShouldWritePending", policy_cc)
        for needle in (
            "kUpgradedManual",
            "kRejectedLowerPriority",
            "ShouldDiscardStale",
            "IsStaleRequest",
        ):
            self.assertIn(needle, text)

    def test_single_openaudiochannel_callsite(self):
        text = APP_CC.read_text(encoding="utf-8", errors="replace")
        opens = [
            ln
            for ln in text.splitlines()
            if "protocol_->OpenAudioChannel(" in ln
            and not ln.strip().startswith("//")
        ]
        self.assertEqual(len(opens), 1, opens)
        self.assertIn("OpenMainAudioChannelExclusive", text)

    def test_no_sync_exclusive_outside_worker(self):
        text = APP_CC.read_text(encoding="utf-8", errors="replace")
        calls = re.findall(r"\bOpenMainAudioChannelExclusive\s*\(", text)
        self.assertEqual(
            len(calls),
            2,
            "expected definition + MainWsOpenTask worker only",
        )

    def test_async_request_paths(self):
        text = APP_CC.read_text(encoding="utf-8", errors="replace")
        self.assertIn("SubmitMainWsOpenRequest", text)
        self.assertIn("MainWsPendingIntent", text)
        self.assertIn("ShouldWritePending", text)
        self.assertIn("main_ws_request_mutex_", text)
        self.assertIn("ws_open_arbiter_", text)
        self.assertNotIn("main_ws_open_inflight_", text)

    def test_main_ws_open_log_tags(self):
        text = APP_CC.read_text(encoding="utf-8", errors="replace")
        for ev in (
            "request",
            "join",
            "upgrade_manual",
            "open_start",
            "open_done",
            "discard_stale",
        ):
            self.assertIn(f'LogMainWsOpenEvent("{ev}"', text)
        self.assertIn("[MAIN_WS_OPEN]", text)
        self.assertIn("event=%s request_id=", text)


class HostRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = find_host_compiler()
        cls.host_rc: int | None = None
        cls.host_output = ""
        if cls.compiler is None:
            return
        try:
            cls.host_rc, cls.host_output = build_and_run_host_test(cls.compiler)
        except RuntimeError as exc:
            cls.host_output = str(exc)
            cls.host_rc = -1

    def test_host_compiler_available(self):
        if self.compiler is None:
            self.fail(
                "未验证: 本机无可用 Host C++ 编译器 (g++/clang++/cl.exe)。"
                "RunUnitTests() 尚未实际运行；请在有编译器的测试机/CI 执行。"
            )

    def test_host_arbiter_exit_zero(self):
        if self.compiler is None:
            self.fail("未验证: 无 Host 编译器，跳过 runtime 不代表通过")
        self.assertNotEqual(self.host_rc, -1, self.host_output)
        self.assertEqual(self.host_rc, 0, self.host_output)
        self.assertIn("ALL HOST TESTS PASSED", self.host_output)


def main() -> int:
    static_suite = unittest.defaultTestLoader.loadTestsFromTestCase(StaticArbiterTests)
    runtime_suite = unittest.defaultTestLoader.loadTestsFromTestCase(HostRuntimeTests)

    static_result = unittest.TextTestRunner(verbosity=2).run(static_suite)
    if not static_result.wasSuccessful():
        print("\n[MAIN_WS_OPEN_HOST] static checks FAILED", file=sys.stderr)
        return 1

    compiler = find_host_compiler()
    if compiler is None:
        print(
            "\n[MAIN_WS_OPEN_HOST] 未验证: 无 g++/clang++/cl.exe；"
            "生产 RunUnitTests() 未实际运行。",
            file=sys.stderr,
        )
        return 2

    print(
        f"\n[MAIN_WS_OPEN_HOST] using {compiler.kind} compiler: {compiler.executable}",
        file=sys.stderr,
    )
    runtime_result = unittest.TextTestRunner(verbosity=2).run(runtime_suite)
    if not runtime_result.wasSuccessful():
        print("\n[MAIN_WS_OPEN_HOST] runtime tests FAILED", file=sys.stderr)
        return 1

    print("\n[MAIN_WS_OPEN_HOST] static + runtime PASSED", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
