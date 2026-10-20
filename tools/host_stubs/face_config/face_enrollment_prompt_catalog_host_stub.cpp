// Host-only allowlist stub so production FaceEnrollmentClient::ValidateGuidedResponse
// can call Find() without linking embedded Ogg assets.
#include "face_enrollment_prompt_catalog.h"

#include <string_view>

namespace {

constexpr std::string_view kAllowed[] = {
    "START",
    "NO_FACE",
    "MOVE_SCREEN_LEFT",
    "MOVE_SCREEN_RIGHT",
    "MOVE_USER_LEFT",
    "MOVE_USER_RIGHT",
    "MOVE_UP",
    "MOVE_DOWN",
    "MOVE_CLOSER",
    "MOVE_BACK",
    "FACE_FORWARD",
    "TOO_DARK",
    "MULTIPLE_FACES",
    "HOLD_STILL",
    "ALIGN_READY",
    "CAPTURE_FRONT",
    "CAPTURE_LEFT",
    "CAPTURE_RIGHT",
    "RECAPTURE_FRONT",
    "RECAPTURE_LEFT",
    "RECAPTURE_RIGHT",
    "UPLOADING",
    "DRAFT_READY",
    "POSE_FAILED",
    "TIMEOUT",
    "CANCELLED",
    "SERVICE_ERROR",
};

FaceEnrollmentPromptCatalog::Prompt g_prompts[sizeof(kAllowed) /
                                              sizeof(kAllowed[0])];
bool g_ready = false;

void EnsurePrompts() {
    if (g_ready) return;
    for (size_t i = 0; i < sizeof(kAllowed) / sizeof(kAllowed[0]); ++i) {
        g_prompts[i].guidance_code = kAllowed[i];
        g_prompts[i].subtitle_text = "";
        g_prompts[i].ogg_opus_asset = {};
    }
    g_ready = true;
}

}  // namespace

const FaceEnrollmentPromptCatalog::Prompt* FaceEnrollmentPromptCatalog::Find(
    std::string_view guidance_code) {
    EnsurePrompts();
    for (auto& prompt : g_prompts) {
        if (prompt.guidance_code == guidance_code) return &prompt;
    }
    return nullptr;
}

bool FaceEnrollmentPromptCatalog::HasAudio(std::string_view) { return false; }

bool FaceEnrollmentPromptCatalog::Present(std::string_view) { return false; }
