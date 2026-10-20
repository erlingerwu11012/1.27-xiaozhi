#ifndef _BMFONT_H_
#define _BMFONT_H_
#include "drawable.h"
#include "font.h"

namespace cubicat
{

class BMFont : public Drawable
{
public:
    DECLARE_RTTI_SUB(BMFont, Drawable);
    static void setFontData(FontData data) { m_sFontData = data; }
    static const FontData& getFontData() { return m_sFontData; }
    static uint8_t getFontSize() { return 20; }
    static Vector2f calculateUTFStringRect(const char* text);
    static SharedPtr<BMFont> create(const Vector2us& size,const char* text, uint16_t color = 0x0) {
        return SharedPtr<BMFont>(NEW BMFont(size, text, color));
    }
    ~BMFont();

    void setColor(uint16_t color);
private:
    BMFont(const Vector2us& size,const char* text, uint16_t color = 0x0);
    uint32_t*       m_pData = nullptr;
    uint32_t        m_PixelCount = 0;
    uint16_t        m_Color = 0;
    bool            m_DataManagedByTexture = false;
    static FontData m_sFontData;
};
} // namespace cubicat
#endif
