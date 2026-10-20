"""Static regression checks for local Chinese voice assets and activation UX.

This suite intentionally needs neither FFmpeg nor an ESP-IDF build.  It guards
the repository contracts that make the already-converted Ogg/Opus files safe to
embed and keeps activation from silently falling through into normal dialogue.
"""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FACE_DIR = ROOT / "main" / "assets" / "face_enrollment"
ZH_DIR = ROOT / "main" / "assets" / "locales" / "zh-CN"

FACE_PROMPTS = {
    "START": "请面向设备。想退出时，说“取消录入人脸”或双击顶部即可。",
    "NO_FACE": "暂时没有检测到人脸，请正对摄像头。",
    "MOVE_SCREEN_LEFT": "请把脸稍微往屏幕左侧移一点。",
    "MOVE_SCREEN_RIGHT": "请把脸稍微往屏幕右侧移一点。",
    "MOVE_USER_LEFT": "请向你自己的左边移动一点，不用转头。",
    "MOVE_USER_RIGHT": "请向你自己的右边移动一点，不用转头。",
    "MOVE_UP": "请把脸的位置向上移一点，继续正对摄像头。",
    "MOVE_DOWN": "请把脸的位置向下移一点，继续正对摄像头。",
    "MOVE_CLOSER": "距离太远，请向设备靠近一点。",
    "MOVE_BACK": "距离太近，请向后退一点。",
    "FACE_FORWARD": "请正对摄像头。",
    "TOO_DARK": "光线太暗，请让光照到脸上，再正对摄像头。",
    "MULTIPLE_FACES": "画面里有多个人，请其他人先离开镜头。",
    "HOLD_STILL": "画面还不够清晰，请保持头部和设备不动，我们再试一次。",
    "ALIGN_READY": "位置刚刚好，我们开始拍照。",
    "CAPTURE_FRONT": "请正对着我，保持不动，正在拍摄。",
    "CAPTURE_LEFT": "请慢慢向左转头，停住就好。",
    "CAPTURE_RIGHT": "请慢慢向右转头，停住就好。",
    "RECAPTURE_FRONT": "这次照片还不合适，请保持正对，我们再拍一次。",
    "RECAPTURE_LEFT": "左侧再拍一次，请慢慢向左转头，停住就好。",
    "RECAPTURE_RIGHT": "右侧再拍一次，请慢慢向右转头，停住就好。",
    "UPLOADING": "照片已经拍好，正在确认，请稍等。",
    "DRAFT_READY": "三张照片都拍好了，正在为你保存。",
    "DRAFT_READY_FRONT_ONLY": "正面照片已经拍好，请到智控台确认姓名并启用。",
    "POSE_FAILED": "这次没拍清楚，我们下次再试吧。",
    "TIMEOUT": "录入时间到了，我们下次再来。",
    "CANCELLED": "好的，已经取消录入。",
    "SERVICE_ERROR": "刚刚出了点小问题，稍后再试一次吧。",
    "UNKNOWN_RESULT": "这一步出了点意外，我们先退出，稍后再试。",
}

SYSTEM_ASSETS = {str(i) for i in range(10)} | {
    "activation",
    "upgrade",
    "wificonfig",
    "server_response_timeout",
}


def opus_head(path: Path) -> tuple[int, int, int]:
    """Return OpusHead version, channels and declared original sample rate."""
    data = path.read_bytes()
    if not data.startswith(b"OggS"):
        raise AssertionError(f"{path.name}: not an Ogg stream")
    offset = data.find(b"OpusHead")
    if offset < 0 or offset + 16 > len(data):
        raise AssertionError(f"{path.name}: missing/truncated OpusHead")
    return data[offset + 8], data[offset + 9], struct.unpack_from("<I", data, offset + 12)[0]


class LocalAudioAssetsAndActivationRegressionTest(unittest.TestCase):
    def test_face_prompt_files_are_complete_and_only_expected(self) -> None:
        actual = {path.stem for path in FACE_DIR.glob("*.ogg")}
        self.assertEqual(set(FACE_PROMPTS), actual)

    def test_every_face_prompt_has_local_copy_and_embedded_asset(self) -> None:
        source = (ROOT / "main" / "face_enrollment_prompt_catalog.cc").read_text(encoding="utf-8")
        for code, subtitle in FACE_PROMPTS.items():
            self.assertIn(f'{{"{code}", "{subtitle}", FACE_PROMPT_ASSET({code})}}', source)
            self.assertIn(f"DECLARE_FACE_PROMPT_ASSET({code})", source)

    def test_all_new_assets_are_mono_ogg_opus(self) -> None:
        paths = [FACE_DIR / f"{name}.ogg" for name in FACE_PROMPTS]
        paths.extend(ZH_DIR / f"{name}.ogg" for name in SYSTEM_ASSETS)
        self.assertEqual(43, len(paths))
        for path in paths:
            version, channels, input_rate = opus_head(path)
            self.assertEqual(1, version, path.name)
            self.assertEqual(1, channels, path.name)
            # The conversion pipeline writes the source speech rate here.
            # Opus internally decodes at 48 kHz, while AudioService reads this
            # 16 kHz declaration and resamples for the board output as needed.
            self.assertEqual(16000, input_rate, path.name)
            self.assertGreater(path.stat().st_size, 128, path.name)

    def test_system_resource_set_and_chinese_timeout_copy(self) -> None:
        for name in SYSTEM_ASSETS:
            self.assertTrue((ZH_DIR / f"{name}.ogg").is_file(), name)
        self.assertFalse((ZH_DIR / "10.ogg").exists())
        language = json.loads((ZH_DIR / "language.json").read_text(encoding="utf-8"))
        self.assertEqual(
            "刚刚网络有点忙，我暂时没能回应，等一会儿再和我说一次吧！",
            language["strings"]["SERVER_RESPONSE_TIMEOUT"],
        )

    def test_cmake_embeds_and_regenerates_language_assets(self) -> None:
        cmake = (ROOT / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("EMBED_FILES ${LANG_SOUNDS} ${COMMON_SOUNDS} ${FACE_ENROLLMENT_SOUNDS}", cmake)
        self.assertIn("${LANG_SOUNDS}", cmake[cmake.index("add_custom_command("):])

    def test_timeout_audio_only_applies_after_a_user_question(self) -> None:
        app = (ROOT / "main" / "application.cc").read_text(encoding="utf-8")
        reply_timeout = app.index("if (awaiting_server_reply_)")
        local_timeout = app.index("OGG_SERVER_RESPONSE_TIMEOUT")
        self.assertGreater(local_timeout, reply_timeout)
        self.assertIn("#if CONFIG_LANGUAGE_ZH_CN", app[reply_timeout:local_timeout])
        websocket = (ROOT / "main" / "protocols" / "websocket_protocol.cc").read_text(encoding="utf-8")
        self.assertNotIn("OGG_SERVER_RESPONSE_TIMEOUT", websocket)

    def test_activation_cannot_start_main_protocol_before_http_200(self) -> None:
        app = (ROOT / "main" / "application.cc").read_text(encoding="utf-8")
        wait_start = app.index("bool Application::WaitForActivation(Ota& ota)")
        wait_end = app.index("void Application::ShowActivationCode", wait_start)
        wait = app[wait_start:wait_end]
        self.assertIn("result == ESP_OK", wait)
        self.assertIn("return true", wait)
        self.assertIn("kActivationPollIntervalMs = 3000", app)
        self.assertIn("kActivationAnnouncementIntervalMs = 120000", app)
        self.assertIn('"您的激活码是："', wait)
        self.assertNotIn("xEventGroupSetBits", wait)
        check = app[app.index("void Application::CheckNewVersion"):wait_start]
        self.assertIn("if (WaitForActivation(ota))", check)

    def test_activation_code_is_exactly_six_digits(self) -> None:
        ota = (ROOT / "main" / "ota.cc").read_text(encoding="utf-8")
        self.assertIn("activation_code_.size() == 6", ota)
        self.assertIn("expected six digits", ota)
        self.assertNotIn("activation_code_.substr(0, 6)", ota)
        self.assertIn("Activation payload prepared", ota)
        self.assertNotIn("Activation payload: %s", ota)


if __name__ == "__main__":
    unittest.main()
