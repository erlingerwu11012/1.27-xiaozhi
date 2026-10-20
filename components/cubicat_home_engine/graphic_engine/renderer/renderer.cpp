#include "renderer.h"
#include "utils/helper.h"
#include <unordered_map>
#include "../definitions.h"
#include "../math/common.h"
#include "utils/logger.h"
#include <string.h>
#include "../math/vector4.h"
#include "utils/home_perf.h"
#include "utils/home_render_options.h"
#include "raster_texture.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"
#include <atomic>
#include <new>
#include <cmath>

using namespace cubicat;

namespace cubicat {
template <class T> struct RasterAllocator {
    using value_type = T;
    RasterAllocator() = default;
    template <class U> RasterAllocator(const RasterAllocator<U> &) {}
    T *allocate(size_t count) {
        auto *ptr = static_cast<T *>(psram_prefered_malloc(count * sizeof(T)));
        if (!ptr)
            throw std::bad_alloc();
        return ptr;
    }
    void deallocate(T *ptr, size_t) { free(ptr); }
    template <class U> bool operator==(const RasterAllocator<U> &) const { return true; }
    template <class U> bool operator!=(const RasterAllocator<U> &) const { return false; }
};
struct EdgeStart {
    uint16_t index;
    int first, last;
};
struct DrawPacket {
    Drawable *drawable = nullptr;
    Polygon2D *polygon = nullptr;
    RasterTexture sampler;
    BlendMode blend = Normal;
    Region region;
    Vector2f scale;
    int angle = 0;
    int16_t sine = 0, cosine = FP_SCALE;
    bool bilinear = false, has_mask = false;
    uint16_t mask = 0;
    const void *image = nullptr;
    Edge *edges = nullptr;
    uint32_t edge_count = 0;
    std::vector<EdgeStart, RasterAllocator<EdgeStart>> starts;
};
struct RasterContext {
    Region clip;
    uint16_t *buffer = nullptr;
    IntersectionPoint *intersections = nullptr;
    uint16_t *active = nullptr;
    size_t capacity = 0;
    HomePerfCounters perf;
    uint32_t elapsed_us = 0;
    bool calibrated = false;
    ~RasterContext() {
        free(intersections);
        free(active);
    }
    bool Reserve(size_t count) {
        if (count <= capacity)
            return true;
        auto *pts = static_cast<IntersectionPoint *>(
            psram_prefered_malloc(count * sizeof(IntersectionPoint)));
        auto *ids = static_cast<uint16_t *>(psram_prefered_malloc(count * sizeof(uint16_t)));
        if (!pts || !ids) {
            free(pts);
            free(ids);
            return false;
        }
        free(intersections);
        free(active);
        intersections = pts;
        active = ids;
        capacity = count;
        return true;
    }
    void Reset(bool sample) {
        if (!calibrated) {
            perf.Calibrate();
            calibrated = true;
        }
        perf.Reset();
        perf.alpha_enabled = sample;
        elapsed_us = 0;
    }
};
struct CachedDrawableRegion { Region region; uint32_t stamp = 0; };
struct RendererState {
    std::unordered_map<uint32_t, CachedDrawableRegion, std::hash<uint32_t>,
        std::equal_to<uint32_t>, RasterAllocator<std::pair<const uint32_t, CachedDrawableRegion>>> region_cache;
    uint32_t region_stamp = 0;
    std::vector<size_t, RasterAllocator<size_t>> edge_buckets;
    std::vector<EdgeStart, RasterAllocator<EdgeStart>> edge_scratch;
    std::vector<DrawPacket, RasterAllocator<DrawPacket>> packets;
    RasterContext primary, worker;
    TaskHandle_t task = nullptr;
    SemaphoreHandle_t done = nullptr;
    std::atomic<bool> stop{false}, cancel{false};
    std::atomic<bool> dual_enabled{false};
    float share = 1.0f / 3, core0_avg = 0, core1_avg = 0;
    uint32_t split_frames = 0;
    bool optimized_enabled = HomeOptimizedDrawing();
};
} // namespace cubicat




#define GEN_INTERSECTION_POINT_2D(edge, pair, worldY) \
    if (edge->yMax != edge->yMin && worldY <= edge->yMax && worldY >= edge->yMin) { \
        IntersectionPoint& point = pair->points[pair->count++]; \
        float yStep = worldY - edge->yMin; \
        point.x = edge->x + edge->dx * yStep; \
        point.u = edge->u + edge->du * yStep; \
        point.v = edge->v + edge->dv * yStep; \
    } \
    edge++;


bool RegionClip(const Region& vp, Region& region, uint16_t* offsetx, uint16_t* offsety) {
    int vpEndx = vp.x + vp.w;                                    
    int vpEndy = vp.y + vp.h;      
    int regEndx = region.x + region.w;
    int regEndy = region.y + region.h;    
    if (offsetx)                          
        *offsetx = 0;       
    if (offsety)                            
        *offsety = 0;                         
    if (region.x >= vpEndx || region.y >= vpEndy || regEndx <= vp.x || regEndy <= vp.y) {
        region.zero();
        return false;                                             
    }
    if (region.x < vp.x)                                              
    {                      
        if (offsetx)                                 
            *offsetx = vp.x - region.x;                                       
        region.x = vp.x;                                              
    }                                                       
    if (region.y < vp.y)                                              
    {                      
        if (offsety)                                 
            *offsety = vp.y - region.y;                                       
        region.y = vp.y;                                              
    }                                                       
    if (regEndx > vpEndx)                                       
    {                                                       
        regEndx = vpEndx;                                       
    }                                                       
    if (regEndy > vpEndy)                                       
    {                                                       
        regEndy = vpEndy;                                       
    }                                                       
    region.w = regEndx - region.x;                                             
    region.h = regEndy - region.y;
    return true;
}

#define WritePixel(x, y, color) \
    backBuffer[y * m_viewport.w + x] = color;

#define ReadPixel(x, y) \
    backBuffer[y * m_viewport.w + x];

#define SamplePixel(texture, x, y, color) \
    if (hasRot) { \
        if (!texture->readPixel(x, y, &color)) \
            continue; \
    } else { \
        color = texture->readPixelUnsafe(x, y); \
    }

#define SamplePixelBilinear(texture, x, y, color) \
    /* 获取四个邻近像素*/ \
    int16_t x0 = (int16_t)x; \
    int16_t y0 = (int16_t)y; \
    int16_t x1 = x0 + 1; \
    int16_t y1 = y0; \
    int16_t x2 = x0; \
    int16_t y2 = y0 + 1; \
    int16_t x3 = x0 + 1; \
    int16_t y3 = y0 + 1; \
    float dx = x - x0; \
    float dy = y - y0; \
    float factorD = dx * dy; \
    float factorC = dy - factorD; \
    float factorB = dx - factorD; \
    float factorA = 1 - dx - factorC; \
    uint32_t color0 = 0; \
    uint32_t color1 = 0; \
    uint32_t color2 = 0; \
    uint32_t color3 = 0; \
    int c = 0; \
    if (texture->readPixel(x0, y0, &color0)) \
        c++; \
    if (texture->readPixel(x1, y1, &color1)) \
        c++; \
    if (texture->readPixel(x2, y2, &color2)) \
        c++; \
    if (texture->readPixel(x3, y3, &color3)) \
        c++; \
    if (c == 0) { \
        continue; \
    } else if (c == 4) { \
        if (hasAlpha) { \
            uint8_t* _color0 = (uint8_t*)&color0; \
            uint8_t* _color1 = (uint8_t*)&color1; \
            uint8_t* _color2 = (uint8_t*)&color2; \
            uint8_t* _color3 = (uint8_t*)&color3; \
            uint8_t* colorOut = (uint8_t*)&color; \
            *(colorOut++) = *(_color0++) * factorA + *(_color1++) * factorB + *(_color2++) * factorC + *(_color3++) * factorD; \
            *(colorOut++) = *(_color0++) * factorA + *(_color1++) * factorB + *(_color2++) * factorC + *(_color3++) * factorD; \
            *(colorOut++) = *(_color0++) * factorA + *(_color1++) * factorB + *(_color2++) * factorC + *(_color3++) * factorD; \
            *(colorOut++) = *(_color0++) * factorA + *(_color1++) * factorB + *(_color2++) * factorC + *(_color3++) * factorD; \
        } else { \
            uint16_t rBlend = (color0 >> 11) * factorA + (color1 >> 11) * factorB + (color2 >> 11) * factorC + (color3 >> 11) * factorD; \
            uint16_t gBlend = ((color0 >> 5) & 0x3F) * factorA + ((color1 >> 5) & 0x3F) * factorB + ((color2 >> 5) & 0x3F) * factorC + ((color3 >> 5) & 0x3F) * factorD; \
            uint16_t bBlend = (color0 & 0x1F) * factorA + (color1 & 0x1F) * factorB + (color2 & 0x1F) * factorC + (color3 & 0x1F) * factorD; \
            color = (rBlend << 11) | (gBlend << 5) | bBlend; \
        } \
    } else { \
        color = color0; \
    }

#define AlphaBlend(x, y, color) \
    /* if pixel has alpha channel. pixel format: RGBA8888*/ \
    if (hasAlpha) { \
        uint8_t _r = color >> 27; \
        uint8_t _g = (color >> 18) & 0x3F; \
        uint8_t _b = (color >> 11) & 0x1F; \
        uint8_t alpha = color & 0xff; \
        if (alpha == 0) { \
            continue; \
        } else if (alpha == 255) { \
            color = (_r << 11) | (_g << 5) | _b; \
        } else { \
            const uint32_t alphaSampleStart = perf.BeginAlphaSample(); \
            auto bgColor = ReadPixel(x, y); \
            if (blendMode == BlendMode::Normal) { \
                uint8_t r = (_r * alpha + (bgColor >> 11) * (255 - alpha)) >> 8; \
                uint8_t g = (_g * alpha + ((bgColor >> 5) & 0x3F) * (255 - alpha)) >> 8; \
                uint8_t b = (_b * alpha + (bgColor & 0x1F) * (255 - alpha)) >> 8; \
                color = (r << 11) | (g << 5) | b; \
            } else if (blendMode == BlendMode::Additive) { \
                uint16_t r = ((_r * alpha) >> 8) + (bgColor >> 11); \
                if (r > 0x1F) \
                    r = 0x1F; \
                uint16_t g = ((_g * alpha) >> 8) + ((bgColor >> 5) & 0x3F); \
                if (g > 0x3F) \
                    g = 0x3F; \
                uint16_t b = ((_b * alpha) >> 8) + (bgColor & 0x1F); \
                if (b > 0x1F) \
                    b = 0x1F; \
                color = (r << 11) | (g << 5) | b; \
            } else {\
                uint8_t r = (_r * ((bgColor >> 11) & 0x1F) / 65025 * alpha + (bgColor >> 11) * (255 - alpha)) >> 8; \
                uint8_t g = (_g * ((bgColor >> 5) & 0x3F) / 65025 * alpha + ((bgColor >> 5) & 0x3F) * (255 - alpha)) >> 8; \
                uint8_t b = (_b * (bgColor & 0x1F) / 65025 * alpha + (bgColor & 0x1F) * (255 - alpha)) >> 8; \
                color = (r << 11) | (g << 5) | b; \
            } \
            perf.EndAlphaSample(alphaSampleStart, color); \
        } \
    } 

#define GetRGB16(color) \
    r = color >> 11; \
    g = (color >> 5) & 0x3f; \
    b = color & 0x1f;

#define GetRGBA32(color) \
    r = color >> 27; \
    g = (color >> 18) & 0x3F; \
    b = (color >> 11) & 0x1F; \
    a = color & 0xff;

#define CombineColor(r, g, b) \
    color = (r << 11) | (g << 5) | b;

#define ColorClamp(r, g, b) \
    if (r > 0x1F) r = 0x1F; \
    if (g > 0x3F) g = 0x3F; \
    if (b > 0x1F) b = 0x1F;

#define RELOCATE_BUFFER(cache, cacheType, cachedCount, newCount) \
    if (cachedCount < newCount) { \
        if (cache) \
            free(cache); \
        cachedCount = newCount; \
        cache = (cacheType*)psram_prefered_malloc(cachedCount * sizeof(cacheType)); \
    }

#define CLAMP_01(x) x = x < 0 ? 0 : (x > 1 ? 1 : x);

Renderer::Renderer(DisplayInterface *backBuffer) : m_pBackBufferInterface(backBuffer) {
    auto buffer = m_pBackBufferInterface->getRenderBuffer();
    m_viewport.x = 0;
    m_viewport.y = 0;
    m_viewport.w = buffer.width;
    m_viewport.h = buffer.height;
    if (!HomeOptimizedDrawing())
        m_pZBuffer =
            (uint16_t *)psram_prefered_malloc(sizeof(uint16_t) * m_viewport.w * m_viewport.h);
    m_state = new RendererState();
    SetHomeDrawingStatus(m_state->optimized_enabled,
                         m_state->optimized_enabled ? "enabled" : "disabled_by_mode");
    if (HomeDualRequested()) {
        m_state->done = xSemaphoreCreateBinary();
        if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) >= 6144 + 16 * 1024 && m_state->done &&
            xTaskCreatePinnedToCore(RasterTaskEntry, "home_raster0", 6144, this, 1, &m_state->task,
                                    0) == pdPASS) {
            m_state->dual_enabled = true;
            SetHomeDualSplit(33);
            SetHomeDualStatus(true, "enabled", uxTaskGetStackHighWaterMark(m_state->task));
        } else {
            SetHomeDualStatus(false, heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < 6144 + 16 * 1024
                                         ? "internal_ram_headroom"
                                         : "task_or_semaphore_allocation_failed");
            LOGW("[RENDERFALLBACK] dual unavailable; use single core");
        }
    } else
        SetHomeDualStatus(false, "disabled_by_mode");
    m_lastTwoFrameHotRegions.push_back(m_hotRegion);
    m_lastTwoFrameHotRegions.push_back(m_hotRegion);
    m_lastTwoFrameVanishedRegions.push_back(Region());
    m_lastTwoFrameVanishedRegions.push_back(Region());
}
Renderer::~Renderer() {
    if (m_state->task) {
        m_state->stop.store(true);
        xTaskNotifyGive(m_state->task);
        // A worker owns borrowed draw packets until it explicitly acknowledges.
        while (xSemaphoreTake(m_state->done, pdMS_TO_TICKS(1000)) != pdTRUE)
            LOGW("Waiting for raster worker to stop");
        m_state->task = nullptr;
    }
    if (m_state->done)
        vSemaphoreDelete(m_state->done);
    SetHomeDualStatus(false, "stopped");
    SetHomeDrawingStatus(false, "stopped");
    delete m_state;
    free(m_pZBuffer);
}

void Renderer::drawPolygon2DScanline(Polygon2D *poly, RasterContext& context) {
    auto& perf = context.perf;
    const auto& clip = context.clip;
    HomePerfScope timing(perf.polygon);
    uint16_t* backBuffer = m_pBackBufferInterface->getRenderBuffer().data;
    auto material = poly->getMaterial();
    auto texture = material->getTexture().get();
    auto blendMode = material->getBlendMode();
    uint16_t texWidth = texture->getTextureSize().x - 1;
    uint16_t texHeight = texture->getTextureSize().y - 1;
    bool hasAlpha = texture->hasAlpha();
    auto bilinear =  material->isBilinearFilter() || poly->getAngle() != 0;
    auto bbox = poly->getRegion();
    // change to screen coordinate
    bbox.y = m_viewport.h - bbox.y;
    RegionClip(clip, bbox, nullptr, nullptr);
    int leftBorder = bbox.x;
    int rightBorder = bbox.x + bbox.w;
    int edgeCount = poly->getEdgeCount();
    auto edgeList = poly->getEdgeList();
    if (static_cast<size_t>(edgeCount) > context.capacity) return;
    for (int y = bbox.y; y < bbox.y + bbox.h; y++) {
        int worldY = m_viewport.h - y;
        int aeCount = 0;
        for (int i=0;i<edgeCount;i++) {
            auto& e = edgeList[i];
            if (worldY <= e.yMax && worldY >= e.yMin) {
                IntersectionPoint* p = &context.intersections[aeCount++];
                p->x = e.x + e.dx * (worldY - e.yMin);
                p->u = e.u + e.du * (worldY - e.yMin);
                p->v = e.v + e.dv * (worldY - e.yMin);
            }
        }
        for (int i = 0; i + 1 < aeCount; i+=2) {
            IntersectionPoint& p0 = context.intersections[i];
            IntersectionPoint& p1 = context.intersections[i + 1];
            if (p0.x > p1.x) {
                std::swap(p0, p1);
            }
            // two intersection points are close than 1 pixel
            float len = p1.x - p0.x;
            if (!(len > 0) || !std::isfinite(len)) continue;
            int startPos = floor(p0.x);
            int endPos = p1.x;
            float u_step = (p1.u - p0.u) / len;
            float v_step = (p1.v - p0.v) / len;
            float u_offset = u_step * (startPos - p0.x);
            float v_offset = v_step * (startPos - p0.x);
            // handle out of bounding box
            if (UNLIKELY(p0.x < bbox.x)) {
                startPos = bbox.x;
                u_offset = u_step * (bbox.x - p0.x);
                v_offset = v_step * (bbox.x - p0.x);
            }
            if (p1.x >= bbox.x + bbox.w) {
                endPos = bbox.x + bbox.w;
            }
            for (int x = startPos; x < endPos; x++) {
                // calc u, v and epsilon for percision correction
                const float epsilon = 0.0001f;
                float u = p0.u + u_offset + epsilon;
                float v = p0.v + v_offset + epsilon;
                CLAMP_01(u);
                CLAMP_01(v);
                u_offset += u_step;
                v_offset += v_step;
                float uCoord = u * texWidth;
                float vCoord = v * texHeight;
                uint8_t r = 0, g = 0, b = 0, a = 255; uint32_t color = 0;
#ifdef CONFIG_ENABLE_BILINEAR_FILTER
                if (bilinear) {
                    SamplePixelBilinear(texture, uCoord, vCoord, color);
                } else {
                    color = texture->readPixelUnsafe(uCoord, vCoord);
                }
#else
                color = texture->readPixelUnsafe(uCoord, vCoord);
#endif
                AlphaBlend(x, y, color);
                WritePixel(x, y, color);
            }
        }
    }
}

void Renderer::drawLegacy(Drawable *drawable, uint16_t* backBuffer, RasterContext& context)
{
    auto& perf = context.perf;
    const auto& clip = context.clip;
    if (drawable->ofA<Polygon2D>()) {
        drawPolygon2DScanline(static_cast<Polygon2D*>(drawable), context);
        return;
    }
    auto material = drawable->getMaterial();
    auto texture = material->getTexture();
    const void *data = texture->getTextureData();
    auto hasMask = material->hasMask();
    auto maskColor = material->getMaskColor();
    auto hasAlpha = texture->hasAlpha();
    auto blendMode = material->getBlendMode();
    int16_t angle = drawable->getAngle();
    const Vector2f&  scale = drawable->getScale();
    bool hasScale = abs(scale.x - 1) > 0.001 || abs(scale.y - 1) > 0.001;
    bool hasRot = angle % 360 != 0;
    const Vector2us& size = texture->getTextureSize();
    // center point of origin picture
    uint16_t originCenterX = (uint16_t)size.x >> 1;
    uint16_t originCenterY = (uint16_t)size.y >> 1;
    //x,y 为图片左上角坐标（屏幕坐标系）
    auto region = drawable->getRegion();
    region.y = m_viewport.h - region.y;
    uint16_t centerX = region.w >> 1;
    uint16_t centerY = region.h >> 1;
    Region imgRegion = region;
    int16_t sina = getSinValue(angle);
    int16_t cosa = getCosValue(angle);
    uint16_t offsetx = 0;
    uint16_t offsety = 0;
    uint8_t r = 0;
    uint8_t g = 0;
    uint8_t b = 0;
    uint8_t a = 255;
    uint32_t color = 0;
    uint32_t col = material->getColor();
    uint8_t col_r = col >> 11;
    uint8_t col_g = col >> 5 & 0x3F;
    uint8_t col_b = col & 0x1F;
    bool colorMix = col != 65535;
    // 只绘制脏区域内的像素
    if (!RegionClip(clip, region, &offsetx, &offsety))
        return;
    if (hasRot || hasScale || texture->getPalette() || hasAlpha) {
        int16_t _offx = offsetx - centerX;
        int16_t _offy = offsety - centerY;
        for (uint16_t j = 0; j < region.h; ++j)
        {
            for (uint16_t i = 0; i < region.w; ++i)
            {
                // _x, _y为缩放旋转后图片的像素坐标,图片中心为原点
#ifdef CONFIG_ENABLE_BILINEAR_FILTER
                float _x = i + _offx;
                float _y = j + _offy;
                if (hasRot) {
                    float _xr = ((int)_x * cosa - (int)_y * sina) / (float)FP_SCALE;
                    float _yr = ((int)_x * sina + (int)_y * cosa) / (float)FP_SCALE;
                    _x = _xr;
                    _y = _yr;
                }
#else
                int16_t _x = i + _offx;
                int16_t _y = j + _offy;
                if (hasRot) {
                    int16_t _xr = (_x * cosa - _y * sina) >> FP_SCALE_SHIFT;
                    int16_t _yr = (_x * sina + _y * cosa) >> FP_SCALE_SHIFT;
                    _x = _xr;
                    _y = _yr;
                }
#endif
                if (hasScale) {
                    _x /= scale.x;
                    _y /= scale.y;
                }
                // 转换到图片坐标
                _x += originCenterX;
                _y += originCenterY;
#ifdef CONFIG_ENABLE_BILINEAR_FILTER
                if (hasRot || hasScale) {
                    SamplePixelBilinear(texture, _x, _y, color);
                } else {
                    SamplePixel(texture, _x, _y, color);
                }
#else
                SamplePixel(texture, _x, _y, color);
#endif
                uint16_t screenX = region.x + i;
                uint16_t screenY = region.y + j;
                AlphaBlend(screenX, screenY, color);
                WritePixel(screenX, screenY, color);
            }
        }
    } else {
        pushImage(imgRegion.x, imgRegion.y, imgRegion.w, imgRegion.h, (const uint16_t *)data, hasMask, maskColor, context);
    }
}
void Renderer::calculateDirtyWindow(const std::vector<DrawablePtr>& drawables) {
    m_dirtyWindow = m_lastTwoFrameHotRegions.front().combine(m_lastTwoFrameHotRegions.back());
    m_dirtyWindow.combine(m_lastTwoFrameVanishedRegions.front().combine(m_lastTwoFrameVanishedRegions.back()));
    if (HomeV2Drawing() && m_state->optimized_enabled) {
        auto &state = *m_state;
        if (++state.region_stamp == 0) {
            for (auto &item : state.region_cache) item.second.stamp = 0;
            ++state.region_stamp;
        }
        m_hotRegion.zero();
        for (const auto &drawable : drawables) {
            auto region = drawable->getRegion();
            region.y = m_viewport.h - region.y;
            auto &cached = state.region_cache[drawable->getId()];
            cached.region = region;
            cached.stamp = state.region_stamp;
            if (drawable->getDirtyAndClear()) m_hotRegion.combine(region);
        }
        Region vanished;
        for (auto it = state.region_cache.begin(); it != state.region_cache.end();) {
            if (it->second.stamp != state.region_stamp) {
                vanished.combine(it->second.region);
                it = state.region_cache.erase(it);
            } else ++it;
        }
        m_dirtyWindow.combine(vanished);
        m_lastTwoFrameVanishedRegions.front() = vanished;
        m_lastTwoFrameVanishedRegions.splice(m_lastTwoFrameVanishedRegions.end(),
                                             m_lastTwoFrameVanishedRegions,
                                             m_lastTwoFrameVanishedRegions.begin());
        RegionClip(m_viewport, m_hotRegion, nullptr, nullptr);
        m_dirtyWindow.combine(m_hotRegion);
        RegionClip(m_viewport, m_dirtyWindow, nullptr, nullptr);
        return;
    }
    std::unordered_map<uint32_t, Region> drawableRegions;
    m_hotRegion.zero();
    for (auto& drawable : drawables) {
        uint32_t id = drawable->getId();
        auto region = drawable->getRegion();
        region.y = m_viewport.h - region.y;
        drawableRegions[id] = region;
        m_lastDrawableRegion.erase(id);
        if (drawable->getDirtyAndClear()) {
            m_hotRegion.combine(region);
        }
    }
    // If drawable regions remain in m_lastDrawableRegion, it means they are no longer exist,
    // and their dirty region should be added to m_dirtyWindow.
    Region vanishedRegion;
    for (auto& pair : m_lastDrawableRegion) {
       vanishedRegion.combine(pair.second);
    }
    m_dirtyWindow.combine(vanishedRegion);
    m_lastTwoFrameVanishedRegions.push_back(vanishedRegion);
    m_lastTwoFrameVanishedRegions.pop_front();
    // swap last drawable region
    m_lastDrawableRegion = drawableRegions;
    RegionClip(m_viewport, m_hotRegion, nullptr, nullptr);
    m_dirtyWindow.combine(m_hotRegion);
    RegionClip(m_viewport, m_dirtyWindow, nullptr, nullptr);
}

void Renderer::drawPacket(const DrawPacket &packet, RasterContext &context) {
    auto &perf = context.perf;
    auto *backBuffer = context.buffer;
    const auto &sampler = packet.sampler;
    const bool hasAlpha = sampler.alpha;
    const auto blendMode = packet.blend;
    if (!sampler.texture || sampler.width <= 0 || sampler.height <= 0)
        return;
    Region bbox = packet.region;
    bbox.y = m_viewport.h - bbox.y;
    if (!RegionClip(context.clip, bbox, nullptr, nullptr))
        return;
    if (packet.polygon) {
        HomePerfScope timing(perf.polygon);
        if (packet.edge_count > context.capacity)
            return;
        size_t next_start = 0, active_count = 0;
        const float texWidth = sampler.width - 1, texHeight = sampler.height - 1;
        if (packet.edge_count == 6)
            ++perf.fast_quads;
        else
            ++perf.active_edge_draws;
        for (int y = bbox.y; y < bbox.y + bbox.h; ++y) {
            if (m_state->cancel.load(std::memory_order_relaxed))
                return;
            const int worldY = m_viewport.h - y;
            int count = 0;
            auto append = [&](uint16_t index) {
                const auto &e = packet.edges[index];
                if (worldY <= e.yMax && worldY >= e.yMin) {
                    auto &out = context.intersections[count++];
                    out.x = e.x + e.dx * (worldY - e.yMin);
                    out.u = e.u + e.du * (worldY - e.yMin);
                    out.v = e.v + e.dv * (worldY - e.yMin);
                }
            };
            if (packet.edge_count == 6) {
                // Unrolled six-edge path (Region quads and two-triangle meshes).
                // Preserve original triangle order and UV interpolation.
                append(0);
                append(1);
                append(2);
                append(3);
                append(4);
                append(5);
            } else {
                // Keep edge IDs sorted, preserving original triangle/blend order.
                while (next_start < packet.starts.size() && packet.starts[next_start].first <= y) {
                    const auto &start = packet.starts[next_start++];
                    if (start.last < y)
                        continue;
                    size_t at = active_count;
                    while (at > 0 && context.active[at - 1] > start.index) {
                        context.active[at] = context.active[at - 1];
                        --at;
                    }
                    context.active[at] = start.index;
                    ++active_count;
                }
                size_t kept = 0;
                for (size_t i = 0; i < active_count; ++i) {
                    const auto index = context.active[i];
                    const auto &e = packet.edges[index];
                    if (worldY < e.yMin)
                        continue;
                    context.active[kept++] = index;
                    append(index);
                }
                active_count = kept;
            }
            for (int i = 0; i + 1 < count; i += 2) {
                auto p0 = context.intersections[i], p1 = context.intersections[i + 1];
                if (p0.x > p1.x)
                    std::swap(p0, p1);
                const float len = p1.x - p0.x;
                if (!(len > 0) || !std::isfinite(len))
                    continue;
                int startPos = std::floor(p0.x), endPos = p1.x;
                const float u_step = (p1.u - p0.u) / len, v_step = (p1.v - p0.v) / len;
                float u_offset = u_step * (startPos - p0.x), v_offset = v_step * (startPos - p0.x);
                if (p0.x < bbox.x) {
                    startPos = bbox.x;
                    u_offset = u_step * (bbox.x - p0.x);
                    v_offset = v_step * (bbox.x - p0.x);
                }
                if (p1.x >= bbox.x + bbox.w)
                    endPos = bbox.x + bbox.w;
                for (int x = startPos; x < endPos; ++x) {
                    float u = p0.u + u_offset + 0.0001f, v = p0.v + v_offset + 0.0001f;
                    CLAMP_01(u);
                    CLAMP_01(v);
                    u_offset += u_step;
                    v_offset += v_step;
                    const float uCoord = u * texWidth, vCoord = v * texHeight;
                    uint32_t color = 0;
#ifdef CONFIG_ENABLE_BILINEAR_FILTER
                    if (packet.bilinear) {
                        if (!sampler.Bilinear(uCoord, vCoord, color))
                            continue;
                    } else
                        color = sampler.ReadUnsafe(uCoord, vCoord);
#else
                    color = sampler.ReadUnsafe(uCoord, vCoord);
#endif
                    AlphaBlend(x, y, color);
                    WritePixel(x, y, color);
                }
            }
        }
        return;
    }
    // Ordinary bitmap path: snapshot all per-draw settings outside pixel loops.
    const bool hasScale =
        std::abs(packet.scale.x - 1) > 0.001 || std::abs(packet.scale.y - 1) > 0.001;
    const bool hasRot = packet.angle % 360 != 0;
    const auto hasMask = packet.has_mask;
    const auto maskColor = packet.mask;
    const int16_t sina = packet.sine, cosa = packet.cosine;
    Region image = packet.region;
    image.y = m_viewport.h - image.y;
    uint16_t offsetx = 0, offsety = 0;
    Region region = image;
    if (!RegionClip(context.clip, region, &offsetx, &offsety))
        return;
    if (!hasRot && !hasScale && !sampler.has_palette && !hasAlpha) {
        const auto *source = static_cast<const uint16_t *>(packet.image);
        if (!source)
            return;
        for (int row = 0; row < region.h; ++row) {
            if (m_state->cancel.load(std::memory_order_relaxed))
                return;
            auto *dest = backBuffer + (region.y + row) * m_viewport.w + region.x;
            const auto *src = source + (offsety + row) * image.w + offsetx;
            if (!hasMask)
                memcpy(dest, src, region.w * sizeof(uint16_t));
            else
                for (int col = 0; col < region.w; ++col)
                    if (src[col] != maskColor)
                        dest[col] = src[col];
        }
        return;
    }
    const int16_t offx = offsetx - (image.w >> 1), offy = offsety - (image.h >> 1);
    for (uint16_t j = 0; j < region.h; ++j) {
        if (m_state->cancel.load(std::memory_order_relaxed))
            return;
        for (uint16_t i = 0; i < region.w; ++i) {
#ifdef CONFIG_ENABLE_BILINEAR_FILTER
            float x = i + offx, y = j + offy;
            if (hasRot) {
                const float xr = ((int)x * cosa - (int)y * sina) / (float)FP_SCALE;
                const float yr = ((int)x * sina + (int)y * cosa) / (float)FP_SCALE;
                x = xr;
                y = yr;
            }
#else
            int16_t x = i + offx, y = j + offy;
            if (hasRot) {
                const int16_t xr = (x * cosa - y * sina) >> FP_SCALE_SHIFT;
                const int16_t yr = (x * sina + y * cosa) >> FP_SCALE_SHIFT;
                x = xr;
                y = yr;
            }
#endif
            if (hasScale) {
                if (packet.scale.x == 0 || packet.scale.y == 0)
                    continue;
                x /= packet.scale.x;
                y /= packet.scale.y;
            }
            x += sampler.width >> 1;
            y += sampler.height >> 1;
            uint32_t color = 0;
#ifdef CONFIG_ENABLE_BILINEAR_FILTER
            if (hasRot || hasScale) {
                if (!sampler.Bilinear(x, y, color))
                    continue;
            } else if (!sampler.Read((int)x, (int)y, color))
                continue;
#else
            if (!sampler.Read((int)x, (int)y, color))
                continue;
#endif
            const uint16_t screenX = region.x + i, screenY = region.y + j;
            AlphaBlend(screenX, screenY, color);
            WritePixel(screenX, screenY, color);
        }
    }
}

void Renderer::drawBand(RasterContext &context) {
    const int64_t start = esp_timer_get_time();
    for (const auto &packet : m_state->packets) {
        if (m_state->cancel.load(std::memory_order_relaxed))
            break;
        drawPacket(packet, context);
    }
    context.elapsed_us = esp_timer_get_time() - start;
}

void Renderer::RasterTaskEntry(void *arg) {
    auto *self = static_cast<Renderer *>(arg);
    auto *state = self->m_state;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        if (state->stop.load())
            break;
        self->drawBand(state->worker);
        SetHomeDualStatus(state->dual_enabled, "enabled", uxTaskGetStackHighWaterMark(nullptr));
        xSemaphoreGive(state->done);
    }
    xSemaphoreGive(state->done);
    vTaskDelete(nullptr);
}

void Renderer::renderObjects(const std::vector<DrawablePtr> &drawables) {
    auto *backBuffer = m_pBackBufferInterface->getRenderBuffer().data;
    {
        HomePerfScope timing(HomePerf().prepare);
        try {
            calculateDirtyWindow(drawables);
        } catch (const std::bad_alloc &) {
            m_state->optimized_enabled = false;
            m_state->dual_enabled = false;
            Region cached_regions;
            for (const auto &entry : m_state->region_cache) cached_regions.combine(entry.second.region);
            m_state->region_cache.clear();
            SetHomeDrawingStatus(false, "region_cache_allocation_failed");
            SetHomeDualStatus(false, "region_cache_allocation_failed");
            for (const auto &d : drawables) d->markDirty();
            calculateDirtyWindow(drawables);
            m_dirtyWindow.combine(cached_regions);
            RegionClip(m_viewport, m_dirtyWindow, nullptr, nullptr);
            LOGW("[RENDERFALLBACK] dirty cache allocation failed; legacy redraw");
        }
        clear();
        for (auto it = m_drawStageListeners.rbegin(); it != m_drawStageListeners.rend(); ++it)
            (*it)->onDrawStart(m_dirtyWindow);
    }
    if (m_dirtyWindow.valid() && backBuffer) {
        auto &state = *m_state;
        bool optimized = state.optimized_enabled;
        size_t max_edges = 1;
        {
            HomePerfScope timing(HomePerf().packet_prepare);
            try {
                if (optimized)
                    state.packets.resize(drawables.size());
                for (size_t n = 0; n < drawables.size(); ++n) {
                    auto *d = drawables[n].get();
                    auto *poly = d->cast<Polygon2D>();
                    const size_t edge_count = poly ? poly->getEdgeCount() : 0;
                    max_edges = std::max(max_edges, edge_count);
                    if (!optimized)
                        continue;
                    auto &packet = state.packets[n];
                    packet.drawable = d;
                    packet.polygon = poly;
                    // These wrappers propagate dirty flags, only on the owner.
                    auto material = d->getMaterial();
                    auto texture = material->getTexture();
                    packet.sampler = RasterTexture{};
                    packet.sampler.Init(texture.get(), true);
                    packet.blend = material->getBlendMode();
                    packet.region = d->getRegion();
                    packet.scale = d->getScale();
                    packet.angle = d->getAngle();
                    packet.sine = getSinValue(packet.angle);
                    packet.cosine = getCosValue(packet.angle);
                    packet.bilinear = material->isBilinearFilter() || packet.angle != 0;
                    packet.has_mask = material->hasMask();
                    packet.mask = material->getMaskColor();
                    packet.image = texture->getTextureData();
                    packet.edge_count = edge_count;
                    packet.edges = poly ? poly->getEdgeList() : nullptr;
                    packet.starts.clear();
                    if (edge_count != 6 && edge_count) {
                        packet.starts.reserve(edge_count);
                        for (size_t i = 0; i < edge_count; ++i) {
                            const auto &e = packet.edges[i];
                            if (!(e.yMax >= e.yMin) || !std::isfinite(e.yMin) ||
                                !std::isfinite(e.yMax))
                                continue;
                            const float raw_first = std::ceil(m_viewport.h - e.yMax),
                                        raw_last = std::floor(m_viewport.h - e.yMin);
                            if (raw_last < m_dirtyWindow.y ||
                                raw_first >= m_dirtyWindow.y + m_dirtyWindow.h) continue;
                            const int first = int(std::max(raw_first, -2147483520.f)),
                                      last = int(std::min(raw_last, 2147483520.f));
                            if (last < m_dirtyWindow.y ||
                                first >= m_dirtyWindow.y + m_dirtyWindow.h)
                                continue;
                            packet.starts.push_back({static_cast<uint16_t>(i), first, last});
                        }
                        HomePerfScope schedule_timing(HomePerf().edge_schedule);
                        if (HomeV2Drawing() && packet.starts.size() >=
                            size_t(std::max(32, int(m_dirtyWindow.h) / 2))) {
                            const int top = m_dirtyWindow.y;
                            const size_t height = m_dirtyWindow.h;
                            state.edge_buckets.assign(height + 1, 0);
                            state.edge_scratch.resize(packet.starts.size());
                            for (auto &start : packet.starts) {
                                start.first = std::max(start.first, top);
                                ++state.edge_buckets[size_t(start.first - top) + 1];
                            }
                            for (size_t row = 1; row <= height; ++row)
                                state.edge_buckets[row] += state.edge_buckets[row - 1];
                            // Input is already in original edge-index order; stable buckets
                            // retain that order when multiple edges start on the same row.
                            for (const auto &start : packet.starts)
                                state.edge_scratch[state.edge_buckets[size_t(start.first - top)]++] = start;
                            std::copy(state.edge_scratch.begin(), state.edge_scratch.end(), packet.starts.begin());
                        } else {
                            std::sort(packet.starts.begin(), packet.starts.end(),
                                      [](const EdgeStart &a, const EdgeStart &b) {
                                          return a.first < b.first ||
                                                 (a.first == b.first && a.index < b.index);
                                      });
                        }
                    }
                }
            } catch (const std::bad_alloc &) {
                optimized = false;
                state.optimized_enabled = false;
                state.dual_enabled = false;
                SetHomeDrawingStatus(false, "packet_allocation_failed");
                SetHomeDualStatus(false, "packet_allocation_failed");
                LOGW("[RENDERFALLBACK] packet allocation failed; use legacy drawing");
                for (auto &d : drawables)
                    if (auto *poly = d->cast<Polygon2D>())
                        max_edges = std::max(max_edges, static_cast<size_t>(poly->getEdgeCount()));
            }
        }
        if (!state.primary.Reserve(max_edges)) {
            SetHomeDrawingStatus(false, "primary_scratch_allocation_failed");
            LOGE("Raster scratch allocation failed; frame not presented");
            return;
        }
        if (optimized)
            SetHomeDrawingStatus(true, "enabled");
        const bool large = m_dirtyWindow.w * m_dirtyWindow.h >= 8192 && m_dirtyWindow.h >= 16;
        bool parallel = optimized && large && state.dual_enabled;
        if (parallel && !state.worker.Reserve(max_edges)) {
            parallel = false;
            state.dual_enabled = false;
            SetHomeDualStatus(false, "scratch_allocation_failed");
            LOGW("[RENDERFALLBACK] worker scratch unavailable; use single core");
        }
        HomePerf().BeginDraw();
        const bool sample = HomePerf().alpha_enabled;
        state.primary.Reset(sample);
        state.primary.buffer = backBuffer;
        state.primary.clip = m_dirtyWindow;
        state.cancel.store(false);
        const int64_t draw_start = esp_timer_get_time();
        if (parallel) {
            state.worker.Reset(sample);
            state.worker.buffer = backBuffer;
            state.worker.clip = m_dirtyWindow;
            const uint16_t rows = std::max<uint16_t>(1, m_dirtyWindow.h * state.share);
            state.worker.clip.h = rows;
            state.primary.clip.y += rows;
            state.primary.clip.h -= rows;
            xTaskNotifyGive(state.task);
            drawBand(state.primary);
            const int64_t wait_start = esp_timer_get_time();
            if (xSemaphoreTake(state.done, pdMS_TO_TICKS(2000)) != pdTRUE) {
                ++HomePerf().dual_timeouts;
                state.cancel.store(true);
                LOGW("[RENDERFALLBACK] raster timeout; cancel then join before redrawing");
                while (xSemaphoreTake(state.done, pdMS_TO_TICKS(1000)) != pdTRUE)
                    LOGW("Waiting for raster cancellation");
                state.dual_enabled = false;
                SetHomeDualStatus(false, "worker_timeout");
                // No worker can touch this frame after the explicit acknowledgement.
                state.cancel.store(false);
                state.primary.Reset(sample);
                state.primary.clip = m_dirtyWindow;
                clear();
                for (auto it = m_drawStageListeners.rbegin(); it != m_drawStageListeners.rend();
                     ++it)
                    (*it)->onDrawStart(m_dirtyWindow);
                drawBand(state.primary);
                parallel = false;
            }
            HomePerf().join_wait.Add(esp_timer_get_time() - wait_start);
            if (parallel) {
                ++HomePerf().dual_frames;
                HomePerf().core0_draw.Add(state.worker.elapsed_us);
                const float t0 = state.worker.elapsed_us, t1 = state.primary.elapsed_us;
                state.core0_avg = state.core0_avg ? state.core0_avg * 0.875f + t0 * 0.125f : t0;
                state.core1_avg = state.core1_avg ? state.core1_avg * 0.875f + t1 * 0.125f : t1;
                if ((++state.split_frames & 15U) == 0 &&
                    std::abs(state.core0_avg - state.core1_avg) >
                        0.1f * std::max(state.core0_avg, state.core1_avg)) {
                    const float denominator =
                        state.share * state.core1_avg + (1 - state.share) * state.core0_avg;
                    if (denominator > 0)
                        state.share = std::max(
                            0.25f, std::min(0.5f, state.share * state.core1_avg / denominator));
                    SetHomeDualSplit(static_cast<uint32_t>(state.share * 100));
                }
            }
        } else if (optimized)
            drawBand(state.primary);
        else {
            const int64_t start = esp_timer_get_time();
            for (auto &d : drawables)
                drawLegacy(d.get(), backBuffer, state.primary);
            state.primary.elapsed_us = esp_timer_get_time() - start;
        }
        HomePerf().draw.Add(esp_timer_get_time() - draw_start);
        HomePerf().core1_draw.Add(state.primary.elapsed_us);
        auto merge = [&](const HomePerfCounters &source) {
            HomePerf().polygon.total_us += source.polygon.total_us;
            HomePerf().polygon.calls += source.polygon.calls;
            HomePerf().polygon.max_us = std::max(HomePerf().polygon.max_us, source.polygon.max_us);
            HomePerf().alpha_pixels += source.alpha_pixels;
            HomePerf().alpha_cycles += source.alpha_cycles;
            HomePerf().alpha_samples += source.alpha_samples;
            HomePerf().fast_quads += source.fast_quads;
            HomePerf().active_edge_draws += source.active_edge_draws;
        };
        merge(state.primary.perf);
        if (parallel)
            merge(state.worker.perf);
        HomePerf().alpha_enabled = false;
        for (auto &d : drawables)
            d->onFinishDraw();
    }
    for (auto it = m_drawStageListeners.rbegin(); it != m_drawStageListeners.rend(); ++it)
        (*it)->onDrawFinish(m_dirtyWindow);
    if (HomeV2Drawing()) {
        m_lastTwoFrameHotRegions.front() = m_hotRegion;
        m_lastTwoFrameHotRegions.splice(m_lastTwoFrameHotRegions.end(), m_lastTwoFrameHotRegions,
                                        m_lastTwoFrameHotRegions.begin());
    } else {
        m_lastTwoFrameHotRegions.push_back(m_hotRegion);
        m_lastTwoFrameHotRegions.pop_front();
    }
}

// x, y, w, h需要是未做viewport裁切的数据，这样才能计算数据偏移
void Renderer::pushImage(int16_t x, int16_t y, uint16_t w, uint16_t h, const uint16_t *data, bool hasMask, uint16_t maskColor, RasterContext& context)
{
    const auto& clip = context.clip;
    auto backBuffer = m_pBackBufferInterface->getRenderBuffer();
    Region region = {x, y, w, h};
    uint16_t offsetx, offsety;
    if (!backBuffer.data || !RegionClip(clip, region, &offsetx, &offsety))
        return;
    // calculate source start index
    int start_index_dest = region.y * m_viewport.w + region.x;
    int start_index_src = offsety * w + offsetx;
    // calculate target start pointer
    auto dest_ptr = backBuffer.data + start_index_dest;
    auto src_ptr = data + start_index_src;
    // calculate bytes per row（2 bytes per pixel）
    int bytes_per_row = w * sizeof(uint16_t);
    // copy data to back buffer
    for (int row = 0; row < region.h; row++)
    {
        for (int col = 0; col < region.w; col++)
        {
            if (hasMask)
            {
                uint16_t color = *(src_ptr);
                if (maskColor != color)
                { // non transparent
                    *dest_ptr = *src_ptr;
                }
            }
            else
            {
                *dest_ptr = *src_ptr;
            }
            src_ptr++;
            dest_ptr++;
        }
        src_ptr += w - region.w;
        dest_ptr += m_viewport.w - region.w;
    }
}

void Renderer::clear() {
    if (!m_bAutoClear)
        return;
    auto backBuffer = m_pBackBufferInterface->getRenderBuffer();
    if (!backBuffer.data) {
        return;
    }
    auto bgColor = m_pBackBufferInterface->getBackgroundColor();
    RegionClip(m_viewport, m_dirtyWindow, nullptr, nullptr);
    const uint16_t maxDepth = 65535; 
    if (m_dirtyWindow == m_viewport) {
        uint32_t count = m_viewport.w * m_viewport.h;
        std::fill(backBuffer.data, backBuffer.data + count, bgColor);
        if(m_pZBuffer)std::fill(m_pZBuffer, m_pZBuffer + count, maxDepth);
    } else {
        for (auto row = m_dirtyWindow.y; row < m_dirtyWindow.y + m_dirtyWindow.h; row++) {
            uint32_t offset = row * m_viewport.w + m_dirtyWindow.x;
            uint16_t* addrBackBuffer = backBuffer.data + offset;
            uint16_t* addrZBuffer = m_pZBuffer ? m_pZBuffer + offset : nullptr;
            std::fill(addrBackBuffer, addrBackBuffer + m_dirtyWindow.w, bgColor);
            if(addrZBuffer)std::fill(addrZBuffer, addrZBuffer + m_dirtyWindow.w, maxDepth);
        }
    }
}
void Renderer::addDrawStageListener(DrawStageListener* listener) {
    for (auto& l : m_drawStageListeners) {  
        if (l == listener) {
            return;
        }
    }
    m_drawStageListeners.push_back(listener);
}
void Renderer::removeDrawStageListener(DrawStageListener* listener) {
    for (auto it = m_drawStageListeners.begin(); it != m_drawStageListeners.end(); it++) {
        if (*it == listener) {
            m_drawStageListeners.erase(it);
            break;
        }
    }
}

// // accelerte sampling by xtensa SIMD
// inline void textureSampling32NormalFast(int16_t* uCoords, int16_t* vCoords, const uint32_t* texture, uint16_t* backBuffer, uint16_t texWidth,
//     int xStart, int xEnd, int y, int viewWidth) {
//     int len = xEnd - xStart;
//     if (len <= 0)
//         return;
//     int16_t* uAddr = uCoords + xStart;
//     int16_t* vAddr = vCoords + xStart;
//     uint16_t* backBufferAddr = backBuffer + viewWidth * y;
//     // a8 u coord, new tex address
//     // a9 v coord, offset
//     // a10 color, bg color
//     // a11 r 
//     // a12 g
//     // a13 b
//     // a14 a, temp
//     // a15 temp
//     __asm__ volatile(
//         "loopnez    %[l], .loop_end     \n"
//             "l16si  a8, %[u], 0         \n" // load uCoords value
//             "l16si  a9, %[v], 0         \n" // load vCoords value
//             "addi.n %[u], %[u], 2       \n" // uAddr++
//             "addi.n %[v], %[v], 2       \n" // vAddr++
//             "mull   a9, a9, %[tw]       \n" //  v * texWidth
//             "add    a9, a9, a8          \n" // texure ptr address offset
//             "slli   a9, a9, 1           \n" // offset * 2
//             "add    a8, %[t], a9        \n" // save new texure address to a8
//             "l32i   a10, a8, 0          \n" // load texture color
//             "srli   a11, a10, 27        \n" // color(32 bit) >> 27 : r
//             "srli   a12, a10, 18        \n" // color(32 bit) >> 18 : g
//             "movi.n a14, 0x3f           \n"
//             "and    a12, a12, a14       \n" // to 6 bit
//             "srli   a13, a10, 11        \n" // color(32 bit) >> 11 : b
//             "movi.n a14, 0x1f           \n"
//             "and    a13, a14, a14       \n" // to 5 bit
//             "movi.n a14, 0xff           \n"
//             "and    a14, a10, a14       \n" // get alpha
//             "l32i   a10, %[b], 0        \n" // load bg color for blending
//             "or     a10, a11, a12       \n"
//             "or     a10, a10, a13     \n"
//             "s16i   a10, %[b], 0                  \n"
//             "addi   %[b], %[b], 2       \n" // back buffer address++
//         ".loop_end:                     \n"
//         :
//         : [u] "a" (uAddr), [v] "a" (vAddr), [t] "a" (texture), [b] "a" (backBufferAddr), [tw] "a" (texWidth), [l] "a" (len)
//         : "memory"
//     );
// }
