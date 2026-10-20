"""Compile and run the production auth-connection state machine on the host."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CJSON = Path("E:/Espressif/frameworks/esp-idf-v5.5.4/components/json/cJSON")


def main():
    out = ROOT / "build" / "auth_connection_host"
    out.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler:
        binary = out / "test.exe"
        cjson_obj = out / "cjson.o"
        subprocess.run(
            ["gcc", "-std=c11", "-O1", "-c", "-I", str(CJSON),
             str(CJSON / "cJSON.c"), "-o", str(cjson_obj)],
            check=True,
        )
        subprocess.run(
            [compiler, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
             "-DAUTH_CONNECTION_HOST", "-I", str(ROOT / "main"), "-I", str(CJSON),
             str(ROOT / "main" / "auth_connection.cc"),
             str(ROOT / "tools" / "auth_connection_host.cpp"),
             str(cjson_obj), "-o", str(binary)],
            check=True,
        )
        result = subprocess.run([str(binary)], text=True, capture_output=True)
    else:
        def wsl_path(path: Path) -> str:
            resolved = path.resolve()
            drive = resolved.drive.rstrip(":").lower()
            tail = resolved.as_posix().split(":", 1)[1]
            return f"/mnt/{drive}{tail}"
        binary = wsl_path(out / "test")
        cjson_obj = wsl_path(out / "cjson.o")
        subprocess.run(
            ["wsl", "-e", "gcc", "-std=c11", "-O1", "-c",
             "-I", wsl_path(CJSON), wsl_path(CJSON / "cJSON.c"), "-o", cjson_obj],
            check=True,
        )
        subprocess.run(
            ["wsl", "-e", "g++", "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
             "-DAUTH_CONNECTION_HOST", "-I", wsl_path(ROOT / "main"),
             "-I", wsl_path(CJSON),
             wsl_path(ROOT / "main" / "auth_connection.cc"),
             wsl_path(ROOT / "tools" / "auth_connection_host.cpp"),
             cjson_obj, "-o", binary],
            check=True,
        )
        result = subprocess.run(["wsl", "-e", binary], text=True, capture_output=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    result.check_returncode()


if __name__ == "__main__":
    main()
