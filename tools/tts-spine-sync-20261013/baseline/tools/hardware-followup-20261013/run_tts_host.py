#!/usr/bin/env python3
"""Run production TTS handlers and capture loop with injected event/read failures."""
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_ws_audio_send_host_test import ROOT, function


def main():
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise SystemExit("Host C++ compiler required (WSL on Windows)")
    source = (Path(__file__).parent / "tts_host.cpp").read_text(encoding="utf-8")
    app = "main/application.cc"
    methods = ["BeginTtsStream", "HandleIncomingTtsAudio", "HandleTtsStop",
               "QueueTtsSubtitle", "UpdateTtsPlayback", "FinishTtsPlayback",
               "ClearTtsStream",
               "AbortSpeaking", "ResumeListeningAfterUserInterrupt",
               "SetListeningMode", "ArmListeningAudio", "EnsureListeningAudio"]
    bodies = [function(app, "void Application::" + name + "(") for name in methods]
    bodies += [function("main/audio/audio_service.cc", "void AudioService::" + name + "(")
               for name in ("AudioInputTask", "EnableVoiceProcessing", "PushTaskToEncodeQueue")]
    source = source.replace("// @METHODS", "\n\n".join(bodies))
    audio = function(app, "protocol_->OnIncomingAudio(") + ");"
    text = (ROOT / app).read_text(encoding="utf-8")
    start = text.index('            const auto* request = cJSON_GetObjectItem(root, "request_id");')
    end = text.index('        } else if (strcmp(type->valuestring, "stt")', start)
    source = source.replace("// @AUDIO_CALLBACK", audio)
    source = source.replace("// @TTS_CALLBACK", text[start:end])
    start = text.index('        } else if (strcmp(type->valuestring, "stt")')
    start = text.index('{', start) + 1
    end = text.index('        } else if (strcmp(type->valuestring, "llm")', start)
    source = source.replace("// @STT_CALLBACK", text[start:end])
    out = ROOT / "build/tts_interrupt_host"
    out.mkdir(parents=True, exist_ok=True)
    generated = out / "test.cpp"
    generated.write_text(source, encoding="utf-8")
    binary = out / "test"
    subprocess.run([compiler, "-std=c++17", "-O1", "-g", "-pthread",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-fno-omit-frame-pointer", "-I"+str(ROOT/"main"), str(generated), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
