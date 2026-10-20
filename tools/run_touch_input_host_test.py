"""Compile production touch snapshots, gestures and backlight with RTOS stubs."""
from pathlib import Path
import os
import shutil
import subprocess
from run_ws_audio_send_host_test import function

ROOT = Path(__file__).resolve().parents[1]

def main():
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        candidates = list((ROOT / "build/host_mingw").glob("**/bin/g++.exe"))
        compiler = str(candidates[0]) if candidates else None
    if not compiler:
        raise SystemExit("Host C++ compiler required")
    out = ROOT / "build/host_tests/touch_input"
    stubs = out / "stubs"
    for name, body in {
        "driver/gpio.h": "#pragma once\nusing gpio_num_t = int;\n",
        "driver/i2c_master.h": "#pragma once\nusing i2c_master_bus_handle_t = void*;\n",
        "esp_log.h": "#pragma once\n#define ESP_LOGI(...) ((void)0)\n#define ESP_LOGD(...) ((void)0)\n#define ESP_LOGW(...) ((void)0)\n",
        "esp_timer.h": "#pragma once\nusing esp_timer_handle_t = void*;\nint esp_timer_stop(esp_timer_handle_t);\nint esp_timer_start_periodic(esp_timer_handle_t, int);\n",
    }.items():
        path = stubs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    source = (ROOT / "tools/test_touch_input_host.cpp").read_text(encoding="utf-8")
    source = source.replace("// @TOUCH", "\n".join(function("main/touch/touch_manager.cc", signature) for signature in (
        "float TouchManager::Clamp01(", "void TouchManager::UpdateState(",
        "void TouchManager::WriteState(", "bool TouchManager::GetState(")))
    source = source.replace("// @DRIVER", function("managed_components/espressif__esp_lcd_touch/esp_lcd_touch.c", "esp_err_t esp_lcd_touch_get_data("))
    source = source.replace("// @BACKLIGHT", "\n".join(function("main/boards/common/backlight.cc", "void Backlight::" + method + "(") for method in (
        "RestoreBrightness", "ApplyTargetLocked", "SetBrightness", "SetTemporaryBrightness", "OnTransitionTimer")))
    path = out / "test.cpp"
    path.write_text(source, encoding="utf-8")
    binary = out / "test.exe"
    env = os.environ.copy()
    env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run([compiler, "-std=c++17", "-O2", "-pthread", "-I" + str(stubs), "-I" + str(ROOT / "main"),
                    str(path), str(ROOT / "main/touch/gesture_engine.cc"), "-o", str(binary)], check=True, env=env)
    subprocess.run([str(binary)], check=True, env=env)

if __name__ == "__main__":
    main()
