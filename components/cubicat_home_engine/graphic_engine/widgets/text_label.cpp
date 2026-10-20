#include "text_label.h"
#include "utils/helper.h"
using namespace cubicat;

TextLabel::TextLabel(uint16_t width, uint16_t height, uint16_t color,const char* text, bool adaptiveSize)
: Widget(width, height), m_Color(color), m_bAdaptiveSize(adaptiveSize) {
    setText(text);
}   

void TextLabel::setText(const char* text) {
    const char* safe_text = text == nullptr ? "" : text;
    if (m_Text == safe_text)
        return;
    m_Text = safe_text;
    clearDrawables();
    if (m_Text.empty()) return;
    if (m_bAdaptiveSize) {
        auto rect = BMFont::calculateUTFStringRect(m_Text.c_str());
        m_width = rect.x;
        m_height = rect.y;
    }
    auto drawable = BMFont::create(
        Vector2us(m_width, m_height), m_Text.c_str(), m_Color);
    attachDrawable(drawable);
    align();
}
