#include "face_enrollment_prompt_catalog.h"

#include "application.h"
#include "board.h"
#include "display.h"

#include <cstddef>
#include <esp_log.h>

namespace {
constexpr const char* kTag = "FaceEnrollPrompt";

// `idf_component_register(EMBED_FILES ...)` emits one pair of linker symbols
// per basename.  The filenames deliberately match the server allowlist codes:
// the server still sends only a code, while all user-visible copy and audio
// remain firmware-owned.
#define DECLARE_FACE_PROMPT_ASSET(code)                                        \
    extern const char code##_ogg_start[] asm("_binary_" #code "_ogg_start"); \
    extern const char code##_ogg_end[] asm("_binary_" #code "_ogg_end");

#define FACE_PROMPT_ASSET(code)                                                \
    std::string_view(code##_ogg_start,                                        \
                     static_cast<size_t>(code##_ogg_end - code##_ogg_start))

DECLARE_FACE_PROMPT_ASSET(START)
DECLARE_FACE_PROMPT_ASSET(NO_FACE)
DECLARE_FACE_PROMPT_ASSET(MOVE_SCREEN_LEFT)
DECLARE_FACE_PROMPT_ASSET(MOVE_SCREEN_RIGHT)
DECLARE_FACE_PROMPT_ASSET(MOVE_USER_LEFT)
DECLARE_FACE_PROMPT_ASSET(MOVE_USER_RIGHT)
DECLARE_FACE_PROMPT_ASSET(MOVE_UP)
DECLARE_FACE_PROMPT_ASSET(MOVE_DOWN)
DECLARE_FACE_PROMPT_ASSET(MOVE_CLOSER)
DECLARE_FACE_PROMPT_ASSET(MOVE_BACK)
DECLARE_FACE_PROMPT_ASSET(FACE_FORWARD)
DECLARE_FACE_PROMPT_ASSET(TOO_DARK)
DECLARE_FACE_PROMPT_ASSET(MULTIPLE_FACES)
DECLARE_FACE_PROMPT_ASSET(HOLD_STILL)
DECLARE_FACE_PROMPT_ASSET(ALIGN_READY)
DECLARE_FACE_PROMPT_ASSET(CAPTURE_FRONT)
DECLARE_FACE_PROMPT_ASSET(CAPTURE_LEFT)
DECLARE_FACE_PROMPT_ASSET(CAPTURE_RIGHT)
DECLARE_FACE_PROMPT_ASSET(RECAPTURE_FRONT)
DECLARE_FACE_PROMPT_ASSET(RECAPTURE_LEFT)
DECLARE_FACE_PROMPT_ASSET(RECAPTURE_RIGHT)
DECLARE_FACE_PROMPT_ASSET(UPLOADING)
DECLARE_FACE_PROMPT_ASSET(DRAFT_READY)
DECLARE_FACE_PROMPT_ASSET(DRAFT_READY_FRONT_ONLY)
DECLARE_FACE_PROMPT_ASSET(POSE_FAILED)
DECLARE_FACE_PROMPT_ASSET(TIMEOUT)
DECLARE_FACE_PROMPT_ASSET(CANCELLED)
DECLARE_FACE_PROMPT_ASSET(SERVICE_ERROR)
DECLARE_FACE_PROMPT_ASSET(UNKNOWN_RESULT)

// Keep this list in protocol order.  Do not add server prose: every visible
// phrase and every Ogg-container Opus asset is selected locally by this table.
const FaceEnrollmentPromptCatalog::Prompt kPrompts[] = {
    {"START", "请面向设备。想退出时，说“取消录入人脸”或双击顶部即可。", FACE_PROMPT_ASSET(START)},
    {"NO_FACE", "暂时没有检测到人脸，请正对摄像头。", FACE_PROMPT_ASSET(NO_FACE)},
    {"MOVE_SCREEN_LEFT", "请把脸稍微往屏幕左侧移一点。", FACE_PROMPT_ASSET(MOVE_SCREEN_LEFT)},
    {"MOVE_SCREEN_RIGHT", "请把脸稍微往屏幕右侧移一点。", FACE_PROMPT_ASSET(MOVE_SCREEN_RIGHT)},
    {"MOVE_USER_LEFT", "请向你自己的左边移动一点，不用转头。", FACE_PROMPT_ASSET(MOVE_USER_LEFT)},
    {"MOVE_USER_RIGHT", "请向你自己的右边移动一点，不用转头。", FACE_PROMPT_ASSET(MOVE_USER_RIGHT)},
    {"MOVE_UP", "请把脸的位置向上移一点，继续正对摄像头。", FACE_PROMPT_ASSET(MOVE_UP)},
    {"MOVE_DOWN", "请把脸的位置向下移一点，继续正对摄像头。", FACE_PROMPT_ASSET(MOVE_DOWN)},
    {"MOVE_CLOSER", "距离太远，请向设备靠近一点。", FACE_PROMPT_ASSET(MOVE_CLOSER)},
    {"MOVE_BACK", "距离太近，请向后退一点。", FACE_PROMPT_ASSET(MOVE_BACK)},
    {"FACE_FORWARD", "请正对摄像头。", FACE_PROMPT_ASSET(FACE_FORWARD)},
    {"TOO_DARK", "光线太暗，请让光照到脸上，再正对摄像头。", FACE_PROMPT_ASSET(TOO_DARK)},
    {"MULTIPLE_FACES", "画面里有多个人，请其他人先离开镜头。", FACE_PROMPT_ASSET(MULTIPLE_FACES)},
    {"HOLD_STILL", "画面还不够清晰，请保持头部和设备不动，我们再试一次。", FACE_PROMPT_ASSET(HOLD_STILL)},
    {"ALIGN_READY", "位置刚刚好，我们开始拍照。", FACE_PROMPT_ASSET(ALIGN_READY)},
    {"CAPTURE_FRONT", "请正对着我，保持不动，正在拍摄。", FACE_PROMPT_ASSET(CAPTURE_FRONT)},
    {"CAPTURE_LEFT", "请慢慢向左转头，停住就好。", FACE_PROMPT_ASSET(CAPTURE_LEFT)},
    {"CAPTURE_RIGHT", "请慢慢向右转头，停住就好。", FACE_PROMPT_ASSET(CAPTURE_RIGHT)},
    {"RECAPTURE_FRONT", "这次照片还不合适，请保持正对，我们再拍一次。", FACE_PROMPT_ASSET(RECAPTURE_FRONT)},
    {"RECAPTURE_LEFT", "左侧再拍一次，请慢慢向左转头，停住就好。", FACE_PROMPT_ASSET(RECAPTURE_LEFT)},
    {"RECAPTURE_RIGHT", "右侧再拍一次，请慢慢向右转头，停住就好。", FACE_PROMPT_ASSET(RECAPTURE_RIGHT)},
    {"UPLOADING", "照片已经拍好，正在确认，请稍等。", FACE_PROMPT_ASSET(UPLOADING)},
    {"DRAFT_READY", "三张照片都拍好了，正在为你保存。", FACE_PROMPT_ASSET(DRAFT_READY)},
    {"DRAFT_READY_FRONT_ONLY", "正面照片已经拍好，请到智控台确认姓名并启用。", FACE_PROMPT_ASSET(DRAFT_READY_FRONT_ONLY)},
    {"POSE_FAILED", "这次没拍清楚，我们下次再试吧。", FACE_PROMPT_ASSET(POSE_FAILED)},
    {"TIMEOUT", "录入时间到了，我们下次再来。", FACE_PROMPT_ASSET(TIMEOUT)},
    {"CANCELLED", "好的，已经取消录入。", FACE_PROMPT_ASSET(CANCELLED)},
    {"SERVICE_ERROR", "刚刚出了点小问题，稍后再试一次吧。", FACE_PROMPT_ASSET(SERVICE_ERROR)},
    {"UNKNOWN_RESULT", "这一步出了点意外，我们先退出，稍后再试。", FACE_PROMPT_ASSET(UNKNOWN_RESULT)},
};

#undef FACE_PROMPT_ASSET
#undef DECLARE_FACE_PROMPT_ASSET
}  // namespace

const FaceEnrollmentPromptCatalog::Prompt* FaceEnrollmentPromptCatalog::Find(
    std::string_view guidance_code) {
    for (const auto& prompt : kPrompts) {
        if (prompt.guidance_code == guidance_code) return &prompt;
    }
    return nullptr;
}

bool FaceEnrollmentPromptCatalog::HasAudio(std::string_view guidance_code) {
    const Prompt* prompt = Find(guidance_code);
    return prompt != nullptr && !prompt->ogg_opus_asset.empty();
}

bool FaceEnrollmentPromptCatalog::Present(std::string_view guidance_code) {
    const Prompt* prompt = Find(guidance_code);
    if (!prompt) return false;

    if (!prompt->subtitle_text.empty()) {
        if (auto* display = Board::GetInstance().GetDisplay()) {
            display->SetChatMessage("assistant", prompt->subtitle_text.data());
        }
    }

    // Keep local playback in this one place.  The existing local player reads
    // the embedded Ogg-container Opus bytes directly; no service TTS is used.
    if (!prompt->ogg_opus_asset.empty()) {
        Application::GetInstance().PlaySound(prompt->ogg_opus_asset);
    }
    ESP_LOGI(kTag, "[FACE_ENROLL] event=prompt code=%.*s subtitle=%d audio=%d",
             static_cast<int>(guidance_code.size()), guidance_code.data(),
             prompt->subtitle_text.empty() ? 0 : 1,
             prompt->ogg_opus_asset.empty() ? 0 : 1);
    return true;
}
