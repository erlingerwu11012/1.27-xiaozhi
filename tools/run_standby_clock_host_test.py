"""Exercise actual display/backlight method bodies with injected hardware failures."""
from pathlib import Path
import os
import shutil
import subprocess
from run_ws_audio_send_host_test import function

ROOT=Path(__file__).resolve().parents[1]

def main():
    compiler=shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        candidates=list((ROOT/"build/host_mingw").glob("**/bin/g++.exe"))
        compiler=str(candidates[0]) if candidates else None
    if not compiler: raise SystemExit("Host C++ compiler required")
    src=(ROOT/"tools/test_standby_clock_host.cpp").read_text(encoding="utf-8")
    src=src.replace("// @DISPLAY", "\n".join(function("main/display/lcd_display.cc", sig) for sig in (
        "void LcdDisplay::NotifyRenderTask(", "void LcdDisplay::RecordDisplayActivity(",
        "bool LcdDisplay::WakeFromStandbyClock(", "void LcdDisplay::TickStandbyClock(",
        "void LcdDisplay::RenderStandbyClock(", "bool LcdDisplay::RestoreHomeFromClock(")))
    src=src.replace("// @BACKLIGHT", "\n".join(function("main/boards/common/backlight.cc", "void Backlight::"+method+"(") for method in (
        "RestoreBrightness", "ApplyTargetLocked", "SetBrightness", "SetTemporaryBrightness", "OnTransitionTimer")))
    src=src.replace("// @ENGINE", "\n".join(function("components/cubicat_home_engine/graphic_engine/embed_game_engine.cpp", "void EmbedGameEngine::"+method+"(") for method in ("update", "resetTiming")))
    src=src.replace("// @GLYPH", function("components/cubicat_home_engine/graphic_engine/drawable/font.cpp", "int getCharIndex("))
    out=ROOT/"build/host_tests/standby_clock";out.mkdir(parents=True,exist_ok=True)
    generated=out/"test.cpp";generated.write_text(src,encoding="utf-8")
    binary=out/"test.exe"
    env=os.environ.copy();env["PATH"]=str(Path(compiler).parent)+os.pathsep+env.get("PATH","")
    subprocess.run([compiler,"-std=c++17","-O2","-pthread","-I"+str(ROOT/"main"),"-I"+str(ROOT/"main/display"),"-I"+str(ROOT/"components/cubicat_home_engine/graphic_engine/drawable"),str(generated),str(ROOT/"main/display/standby_clock.cc"),str(ROOT/"components/cubicat_home_engine/graphic_engine/drawable/gb2312font_20.cpp"),"-o",str(binary)],check=True,env=env)
    subprocess.run([str(binary),str(out/"clock.ppm")],check=True,env=env)
    from PIL import Image
    Image.open(out/"clock.ppm").save(out/"clock-320.png")
    print("Native renderer preview:",out/"clock-320.png")

if __name__=="__main__":main()
