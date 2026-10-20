#pragma once

#include <cstdint>

// Temporary, intentionally compact serial trace for manual device validation.
// Callers must use static, non-sensitive outcome/reason strings. Do not pass
// reminder text, display names, person ids, session ids, URLs, tokens, or any
// user payload here.
namespace test_observability {

void Event(const char* domain, const char* event, uint32_t presence_generation,
           const char* outcome, const char* reason, int value = -1);

}  // namespace test_observability
