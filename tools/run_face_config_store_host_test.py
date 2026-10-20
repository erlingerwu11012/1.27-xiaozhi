#!/usr/bin/env python3
"""Build and run production C++ host tests for face_config_store.

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
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main"
STUBS = ROOT / "tools" / "host_stubs" / "face_config"
STORE_HOST = ROOT / "tools" / "test_face_config_store_host.cpp"
RUNTIME = STUBS / "face_config_host_runtime.cpp"
CATALOG_STUB = STUBS / "face_enrollment_prompt_catalog_host_stub.cpp"
STORE_CC = MAIN / "face_config_store.cc"
CLIENT_CC = MAIN / "face_enrollment_client.cc"
SETTINGS_CC = MAIN / "settings.cc"
HELPER_H = ROOT / "components" / "cubicat_home_engine" / "utils" / "helper.h"
HELPER_TEST = ROOT / "tools" / "graphic_benchmark_macro_host_test.cpp"
OUT_DIR = ROOT / "build" / "host_tests"
STORE_OUT = OUT_DIR / "test_face_config_store_host.exe"
HELPER_OUT = OUT_DIR / "graphic_benchmark_macro_host_test.exe"

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
    str(ROOT / "build" / "host_mingw" / "llvm-mingw-20250613-ucrt-x86_64" / "bin" / "g++.exe"),
    str(ROOT / "build" / "host_mingw" / "mingw64" / "bin" / "g++.exe"),
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
        return CompilerInfo("msvc", cl_path, ["/EHsc", "/std:c++17", "/nologo"])
    return None


def find_host_compiler() -> CompilerInfo | None:
    extra = []
    extra.extend(glob.glob(str(ROOT / "build" / "host_mingw" / "**" / "g++.exe"), recursive=True))
    extra.extend(glob.glob(str(ROOT / "build" / "host_mingw" / "**" / "clang++.exe"), recursive=True))
    for candidate in COMPILER_CANDIDATES + extra:
        path = shutil.which(candidate) if os.path.sep not in candidate else candidate
        if path and Path(path).exists():
            return CompilerInfo("gnu", path)
    return find_msvc_cl()


def run_cmd(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}):\n{' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}"
        )


def build_and_run(compiler: CompilerInfo) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (STORE_OUT, HELPER_OUT):
        if path.exists():
            path.unlink()

    helper_include = str(HELPER_H.parent)
    if compiler.kind == "msvc":
        store_cmd = [
            compiler.executable,
            *compiler.extra_args,
            "/DFACE_CONFIG_HOST_TEST",
            f"/I{STUBS}",
            f"/I{MAIN}",
            f"/Fe:{STORE_OUT}",
            str(STORE_HOST),
            str(RUNTIME),
            str(CATALOG_STUB),
            str(STORE_CC),
            str(CLIENT_CC),
            str(SETTINGS_CC),
        ]
        helper_cmd = [
            compiler.executable,
            *compiler.extra_args,
            f"/I{helper_include}",
            f"/Fe:{HELPER_OUT}",
            str(HELPER_TEST),
        ]
    else:
        store_cmd = [
            compiler.executable,
            "-std=c++17",
            "-pthread",
            "-Wno-unused-function",
            "-Wno-unused-variable",
            "-DFACE_CONFIG_HOST_TEST",
            f"-I{STUBS}",
            f"-I{MAIN}",
            str(STORE_HOST),
            str(RUNTIME),
            str(CATALOG_STUB),
            str(STORE_CC),
            str(CLIENT_CC),
            str(SETTINGS_CC),
            "-o",
            str(STORE_OUT),
        ]
        helper_cmd = [
            compiler.executable,
            "-std=c++17",
            f"-I{helper_include}",
            str(HELPER_TEST),
            "-o",
            str(HELPER_OUT),
        ]

    run_cmd(store_cmd)
    run_cmd(helper_cmd)

    store_run = subprocess.run([str(STORE_OUT)], capture_output=True, text=True)
    helper_run = subprocess.run([str(HELPER_OUT)], capture_output=True, text=True)
    output = store_run.stdout + store_run.stderr + helper_run.stdout + helper_run.stderr
    if store_run.returncode != 0 or helper_run.returncode != 0:
        raise RuntimeError(f"host runtime failed:\n{output}")
    if "ALL HOST TESTS PASSED" not in store_run.stdout:
        raise RuntimeError(f"store host tests missing pass banner:\n{output}")
    return output


class StaticContractTests(unittest.TestCase):
    def test_production_sources_used(self):
        store = STORE_CC.read_text(encoding="utf-8")
        client = CLIENT_CC.read_text(encoding="utf-8")
        helper = HELPER_H.read_text(encoding="utf-8")
        host_test = STORE_HOST.read_text(encoding="utf-8")
        helper_test = HELPER_TEST.read_text(encoding="utf-8")
        self.assertIn("std::lock_guard<std::mutex> lock(s_init_mu)", store)
        self.assertIn("IoResult::Transient", store)
        self.assertIn("ReadStatus::Error", store)
        self.assertIn("op=validate", client)
        self.assertIn("LoadWebsocketUrl(&main_url)", client)
        self.assertIn('#include "helper.h"', helper_test)
        self.assertNotIn("#define BENCHMARK", helper_test)
        self.assertIn("do { code; } while (0);", helper)
        self.assertIn("TryGetInt", store)
        self.assertIn("TryGetBool", store)
        self.assertIn("nvs_get_i32", SETTINGS_CC.read_text(encoding="utf-8"))
        self.assertIn("nvs_get_u8", SETTINGS_CC.read_text(encoding="utf-8"))
        self.assertFalse((STUBS / "settings.h").exists())
        runtime = (STUBS / "face_config_host_runtime.cpp").read_text(encoding="utf-8")
        self.assertIn("nvs_get_i32", runtime)
        self.assertIn("nvs_get_u8", runtime)
        self.assertNotIn("class Settings", runtime)
        self.assertIn("ValidV2Config", host_test)
        self.assertIn("HostNvsGetI32Calls", host_test)
        self.assertIn("TestV1MissingIntBoolKeysUseDefaults", host_test)
        self.assertIn("TestValidateGuidedResponseCompletionAndQuota", host_test)
        self.assertTrue(CATALOG_STUB.exists())
        self.assertNotIn("FaceEnrollmentClient::GetInstance().ResetForTest();\n        face_config_host::SetNvsGetError(\"face_enrollment\", field.key, false)", host_test)


class HostRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = find_host_compiler()
        cls.host_output = ""
        cls.host_error = None
        if cls.compiler is None:
            return
        try:
            cls.host_output = build_and_run(cls.compiler)
        except RuntimeError as exc:
            cls.host_error = str(exc)

    def test_host_compiler_available(self):
        if self.compiler is None:
            self.skipTest(
                "未验证: 本机无可用 Host C++ 编译器 (g++/clang++/cl.exe)"
            )

    def test_host_runtime_passed(self):
        if self.compiler is None:
            self.skipTest("未验证: 无 Host 编译器，未实际运行生产 C++")
        self.assertIsNone(self.host_error, self.host_error)
        self.assertIn("ALL HOST TESTS PASSED", self.host_output)


def main() -> int:
    compiler = find_host_compiler()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if compiler is None:
        print(
            "\n[FACE_CONFIG_HOST] 未验证: 无 g++/clang++/cl.exe；"
            "生产 C++ 执行器测试未实际运行。",
            file=sys.stderr,
        )
        return 2
    if not result.wasSuccessful():
        return 1
    print("\n[FACE_CONFIG_HOST] production C++ runtime PASSED", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
