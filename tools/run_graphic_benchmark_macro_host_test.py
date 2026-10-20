#!/usr/bin/env python3
"""Compile and run the production helper.h BENCHMARK macros."""
from pathlib import Path
import sys

from run_face_config_store_host_test import find_host_compiler, build_and_run


def main() -> int:
    compiler = find_host_compiler()
    if compiler is None:
        print("未验证: 本机无可用 Host C++ 编译器，未编译生产 helper.h")
        return 2
    build_and_run(compiler)
    print("graphic_benchmark_macro_host_test: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
