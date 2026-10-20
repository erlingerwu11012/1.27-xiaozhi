#pragma once

// One geometry for the off-screen texture, scene placement and touch targets.
namespace mcp_card_layout {
constexpr int kWidth = 294;
constexpr int kSummaryHeight = 116;
constexpr int kExpandedHeight = 208;
constexpr int kRadius = 16;
constexpr int kInset = 14;
constexpr int kButtonHeight = 40;
constexpr int kButtonGap = 8;

constexpr int Height(bool expanded) {
    return expanded ? kExpandedHeight : kSummaryHeight;
}

constexpr int ButtonTop() {
    return kExpandedHeight - kInset - kButtonHeight;
}

constexpr int ButtonWidth() {
    return (kWidth - 2 * kInset - kButtonGap) / 2;
}

constexpr int ButtonLeft(int index) {
    return kInset + index * (ButtonWidth() + kButtonGap);
}

constexpr int kTertiaryWidth = 100;
constexpr int kTertiaryHeight = 22;
constexpr int kTertiaryLeft = kWidth - kInset - kTertiaryWidth;
constexpr int kTertiaryTop = ButtonTop() - kTertiaryHeight - 6;

constexpr int ActionAreaTop(bool has_tertiary) {
    return has_tertiary ? kTertiaryTop : ButtonTop();
}

// -1 means padding/gap, not a button. Coordinates are relative to the card.
inline int HitButton(float x, float y, bool has_tertiary) {
    if (has_tertiary && x >= kTertiaryLeft && x < kTertiaryLeft + kTertiaryWidth &&
        y >= kTertiaryTop && y < kTertiaryTop + kTertiaryHeight) return 2;
    if (y < ButtonTop() || y >= ButtonTop() + kButtonHeight) return -1;
    for (int index = 0; index < 2; ++index) {
        const int left = ButtonLeft(index);
        if (x >= left && x < left + ButtonWidth()) return index;
    }
    return -1;
}
}  // namespace mcp_card_layout
