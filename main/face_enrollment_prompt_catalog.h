#pragma once

#include <string_view>

// Local, deterministic user guidance for guided face enrollment.  The server
// supplies only the code; user-visible copy and audio stay on the device.
//
// The table is the product-owned allowlist for copy and embedded Ogg/Opus
// resources.  Filling it never changes the wire protocol or state machine.
class FaceEnrollmentPromptCatalog {
public:
    struct Prompt {
        std::string_view guidance_code;
        std::string_view subtitle_text;
        std::string_view ogg_opus_asset;
    };

    // Returns nullptr for an unrecognised service code.
    static const Prompt* Find(std::string_view guidance_code);
    static bool HasAudio(std::string_view guidance_code);

    // Shows local copy in the ordinary conversation subtitle dock and sends
    // the embedded Ogg/Opus asset to the existing local player.  It returns
    // true if the code belongs to the allowlist.
    static bool Present(std::string_view guidance_code);
};
