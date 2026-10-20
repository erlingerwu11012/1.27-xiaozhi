#include "graphic_engine/renderer/renderer.h"
#include "renderer_reference.h"
#include "renderer_previous.h"
#include "home_lcd_stream.h"
#include "standby_clock.h"
#include "home_frame_pipeline.h"
#include "utils/home_render_options.h"
#include "host_runtime.h"
#include "spine_node.h"
#include <spine/spine.h>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <thread>
using namespace cubicat;
namespace fs = std::filesystem;
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x))                                                                                  \
            throw std::runtime_error(std::string("CHECK failed: ") + #x + " at line " +            \
                                     std::to_string(__LINE__));                                    \
    } while (0)
struct Surface : DisplayInterface, DrawStageListener {
    std::vector<uint16_t> pixels = std::vector<uint16_t>(320 * 320 + 32, 0xabcd);
    unsigned starts = 0, finishes = 0;
    uint16_t *Data() { return pixels.data() + 16; }
    RenderBuffer getRenderBuffer() override { return {Data(), 320, 320}; }
    uint16_t getBackgroundColor() override { return 0x0841; }
    void onDrawStart(const Region &) override { ++starts; }
    void onDrawFinish(const Region &) override { ++finishes; }
    void Guards() {
        for (int i = 0; i < 16; ++i)
            CHECK(pixels[i] == 0xabcd && pixels[320 * 320 + 16 + i] == 0xabcd);
    }
};
struct CountPoly : Polygon2D {
    DECLARE_RTTI_SUB(CountPoly, Polygon2D);
    int count = 0;
    std::thread::id owner = std::this_thread::get_id();
    explicit CountPoly(Mesh2DPtr mesh) : Polygon2D(mesh) {}
    void onFinishDraw() override {
        CHECK(owner == std::this_thread::get_id());
        ++count;
    }
};
TexturePtr MakeTexture(bool alpha, int frame = 0, bool palette = false) {
    constexpr int w = 32, h = 32;
    if (palette) {
        auto *data = static_cast<uint16_t *>(malloc(w * h * 2));
        for (int i = 0; i < w * h; ++i)
            data[i] = i % 3 ? 0x8000 : 0x0;
        static uint16_t colors[] = {0x001f, 0xf800};
        return Texture::create(w, h, data, true, 1, 1, colors, 16, false);
    }
    if (alpha) {
        auto *data = static_cast<uint32_t *>(malloc(w * h * 4));
        for (int i = 0; i < w * h; ++i)
            data[i] = ((i * 17U + 11U) & 255) << 24 | ((i * 3U + 17U) & 255) << 16 |
                      ((i * 7U + 3U) & 255) << 8 |
                      (i % 7 == 0   ? 0
                       : i % 5 == 0 ? 255
                                    : 117);
        return Texture::create(w, h, data, true, 1, 1, nullptr, 32, true);
    }
    auto *data = static_cast<uint16_t *>(malloc(w * h * 2));
    for (int i = 0; i < w * h; ++i)
        data[i] = static_cast<uint16_t>(i * 53 + 0x1090);
    auto texture = Texture::create(w, h, data, true, 1, frame ? 2 : 1);
    if (frame)
        texture->setFrame(1);
    return texture;
}
DrawablePtr MeshDrawable(const std::vector<Vertex2> &vertices, const std::vector<uint16_t> &indices,
                         TexturePtr texture, Vector2f pos = {160, 160}, Vector2f scale = {1, 1},
                         int angle = 0, cubicat::BlendMode blend = Normal, bool bilinear = true) {
    auto *v = static_cast<Vertex2 *>(malloc(vertices.size() * sizeof(Vertex2)));
    // Vertex2 is the same production type; start its lifetime before assignment.
    for (size_t i = 0; i < vertices.size(); ++i)
        new (&v[i]) Vertex2(vertices[i]);
    auto *ids = static_cast<uint16_t *>(malloc(indices.size() * 2));
    memcpy(ids, indices.data(), indices.size() * 2);
    auto poly = SharedPtr<CountPoly>(
        new CountPoly(Mesh2D::create(v, vertices.size(), ids, indices.size(), true)));
    auto mat = poly->getMaterial();
    mat->setTexture(texture);
    mat->setBilinearFilter(bilinear);
    mat->setBlendMode(blend);
    poly->update(pos, scale, angle);
    poly->markDirty();
    return poly;
}
std::vector<Vertex2> Quad(float w = 130, float h = 125, bool rotated_uv = false) {
    std::vector<Vertex2> v(4);
    float xy[] = {-w / 2, -h / 2, -w / 2, h / 2, w / 2, h / 2, w / 2, -h / 2};
    float uv[] = {0, 1, 0, 0, 1, 0, 1, 1};
    for (int i = 0; i < 4; ++i) {
        v[i].x = xy[i * 2];
        v[i].y = xy[i * 2 + 1];
        v[i].u = uv[i * 2];
        v[i].v = uv[i * 2 + 1];
        if (rotated_uv) {
            float u = v[i].u;
            v[i].u = v[i].v;
            v[i].v = 1 - u;
        }
    }
    return v;
}
std::vector<DrawablePtr> Synthetic(int seed) {
    std::vector<DrawablePtr> scene;
    for (int n = 0; n < 5; ++n) {
        auto q = Quad(143 + n * 12, 145 - n * 6, n == 3);
        auto t = n == 4 ? TexturePtr(new SolidTexture(0x5af6)) : MakeTexture(n != 1, 0, n == 2);
        scene.push_back(MeshDrawable(q, {0, 1, 2, 0, 2, 3}, t, {150.25f + n * 13, 180.5f - n * 11},
                                     {n == 1 ? -1.13f : 1.12f, n == 2 ? -0.95f : 0.92f},
                                     (seed * 13 + n * 9) % 360, static_cast<cubicat::BlendMode>(n % 3),
                                     n != 1));
    }
    std::vector<Vertex2> verts;
    std::vector<uint16_t> ids;
    for (int row = 0; row < 6; ++row)
        for (int col = 0; col < 7; ++col) {
            Vertex2 v;
            v.x = col * 35 - 100 + std::sin(row + seed * .1f) * 9;
            v.y = row * 37 - 90 + std::cos(col + seed * .2f) * 5;
            v.u = col / 6.f;
            v.v = row / 5.f;
            verts.push_back(v);
        }
    for (int row = 0; row < 5; ++row)
        for (int col = 0; col < 6; ++col) {
            uint16_t a = row * 7 + col;
            ids.insert(ids.end(), {a, uint16_t(a + 1), uint16_t(a + 7), uint16_t(a + 1),
                                   uint16_t(a + 8), uint16_t(a + 7)});
        }
    scene.push_back(
        MeshDrawable(verts, ids, MakeTexture(true), {160, 175}, {1.22f, 1.17f}, seed % 29));
    // Text-like bitmap overlay, masked RGB565 image, and sprite sheet frame.
    for (int n = 0; n < 4; ++n) {
        auto d = Drawable::create();
        auto mat = d->getMaterial();
        mat->setTexture(MakeTexture(n == 0, n == 3, n == 2));
        mat->setMask(n == 1);
        mat->setMaskColor(0x1090);
        d->update({n == 1 ? 3.f : 100.f + n * 37, 32.f + n * 8},
                  {n == 0 ? -1.15f : 1.f, n == 0 ? 1.12f : 1.f}, n == 0 ? 27 : 0);
        d->markDirty();
        scene.push_back(d);
    }
    // Degenerate triangles must neither overflow scratch nor divide by zero.
    scene.push_back(MeshDrawable(Quad(0, 90), {0, 1, 2, 0, 2, 3}, MakeTexture(true)));
    return scene;
}
std::vector<uint16_t> Capture(HomeRenderMode mode, std::vector<DrawablePtr> &scene,
                              bool force_packet_failure = false, bool worker_timeout = false) {
    ConfigureHomeRenderMode(mode);
    HomePerf().Reset();
    Surface surface;
    {
        Renderer renderer(&surface);
        renderer.addDrawStageListener(&surface);
        if (force_packet_failure)
            HostFailPsram.store(true);
        if (worker_timeout)
            HostNotifyDelay.store(2100);
        for (auto &d : scene)
            d->markDirty();
        renderer.renderObjects(scene);
        for (auto &d : scene)
            if (auto *p = d->cast<CountPoly>())
                CHECK(p->count == 1);
        CHECK(surface.starts >= 1);
        CHECK(surface.finishes == 1);
        surface.Guards();
        if (worker_timeout)
            CHECK(HomePerf().dual_timeouts == 1 && !GetHomeRenderStatus().dual_enabled);
    }
    return {surface.Data(), surface.Data() + 320 * 320};
}
std::vector<uint16_t> CaptureSavedBaseline(std::vector<DrawablePtr> &scene) {
    Surface surface;
    {
        ReferenceRenderer renderer(&surface);
        renderer.addDrawStageListener(&surface);
        for (auto &d : scene)
            d->markDirty();
        renderer.renderObjects(scene);
        surface.Guards();
    }
    return {surface.Data(), surface.Data() + 320 * 320};
}
std::vector<uint16_t> CapturePrevious(std::vector<DrawablePtr> &scene) {
    Surface surface;
    ConfigureHomeRenderMode(HomeRenderMode::Combined);
    {
        PreviousRenderer renderer(&surface);
        for (auto &d : scene) d->markDirty();
        renderer.renderObjects(scene);
        surface.Guards();
    }
    return {surface.Data(), surface.Data() + 320 * 320};
}
void Compare(const std::vector<uint16_t> &a, const std::vector<uint16_t> &b,
             const std::string &label) {
    CHECK(a.size() == b.size());
    size_t count = 0, first = 0;
    for (size_t i = 0; i < a.size(); ++i)
        if (a[i] != b[i]) {
            if (count++ == 0)
                first = i;
        }
    if (count)
        throw std::runtime_error(label + ": " + std::to_string(count) +
                                 " differing pixels; first=" + std::to_string(first) + " a=" +
                                 std::to_string(a[first]) + " b=" + std::to_string(b[first]));
}
void TestSynthetic() {
    for (int seed = 0; seed < 40; ++seed) {
        auto base = Synthetic(seed);
        auto image = Capture(HomeRenderMode::Baseline, base);
        auto saved_scene = Synthetic(seed);
        Compare(image, CaptureSavedBaseline(saved_scene),
                "saved 75fbc1ba baseline pose " + std::to_string(seed));
        auto previous_scene = Synthetic(seed);
        Compare(image, CapturePrevious(previous_scene), "saved 26cfcc19 synthetic");
        for (auto profile : {HomeRenderProfile::V1, HomeRenderProfile::V2}) {
        ConfigureHomeRenderOptions(profile, 30, true);
        for (auto mode : {HomeRenderMode::Render, HomeRenderMode::Pipeline, HomeRenderMode::Dual,
                          HomeRenderMode::Combined}) {
            auto next = Synthetic(seed);
            Compare(image, Capture(mode, next),
                    "synthetic " + std::to_string(seed) + " " + HomeRenderModeName(mode));
        }
        }
    }
    auto base = Synthetic(4);
    auto image = Capture(HomeRenderMode::Baseline, base);
    auto fallback = Synthetic(4);
    Compare(image, Capture(HomeRenderMode::Combined, fallback, true), "packet allocation fallback");
    auto timeout = Synthetic(4);
    Compare(image, Capture(HomeRenderMode::Combined, timeout, false, true),
            "worker timeout cancel/join/redraw");
    HostFailTask = "home_raster0";
    auto no_task = Synthetic(4);
    Compare(image, Capture(HomeRenderMode::Combined, no_task), "worker task allocation fallback");
    HostFailTask.clear();
    // A small region bypasses the worker.
    ConfigureHomeRenderMode(HomeRenderMode::Combined);
    HomePerf().Reset();
    {
        Surface s;
        Renderer r(&s);
        auto d = MeshDrawable(Quad(30, 20), {0, 1, 2, 0, 2, 3}, MakeTexture(true));
        r.renderObjects({d});
        CHECK(HomePerf().dual_frames == 0);
    }
    std::cout << "PASS synthetic: 40 poses x 2 profiles x 4 modes, masks/palette/special/sprite/rotation/UV "
                 "rotation/flips/alpha/blends/mesh/text-like "
                 "overlay/degenerate/clipping/guards/callbacks\n";
    std::cout << "PASS raster fallback: packet allocation, task creation, worker timeout, "
                 "small-region bypass\n";
}
void TestPersistent() {
    ConfigureHomeRenderMode(HomeRenderMode::Baseline);
    Surface base_surface;
    Renderer base(&base_surface);
    ConfigureHomeRenderMode(HomeRenderMode::Combined);
    Surface fast_surface;
    Renderer fast(&fast_surface);
    auto bg_base =
        MeshDrawable(Quad(320, 320), {0, 1, 2, 0, 2, 3}, TexturePtr(new SolidTexture(0x0841)));
    auto bg_fast =
        MeshDrawable(Quad(320, 320), {0, 1, 2, 0, 2, 3}, TexturePtr(new SolidTexture(0x0841)));
    unsigned dual_frames = 0;
    for (int frame = 0; frame < 100; ++frame) {
        auto a = Synthetic(frame), b = Synthetic(frame);
        a.insert(a.begin(), bg_base);
        b.insert(b.begin(), bg_fast);
        if (frame % 7 == 0) {
            a.erase(a.begin() + 3);
            b.erase(b.begin() + 3);
        }
        // Baseline redraws the full background. Optimized dirty regions retain
        // old pixels correctly when a slot disappears or resources are replaced.
        bg_base->markDirty();
        base.renderObjects(a);
        HomePerf().Reset();
        fast.renderObjects(b);
        Compare({base_surface.Data(), base_surface.Data() + 320 * 320},
                {fast_surface.Data(), fast_surface.Data() + 320 * 320},
                "persistent adaptive split frame " + std::to_string(frame));
        dual_frames += HomePerf().dual_frames;
        CHECK(GetHomeRenderStatus().core0_share_pct >= 25 &&
              GetHomeRenderStatus().core0_share_pct <= 50);
        base_surface.Guards();
        fast_surface.Guards();
    }
    CHECK(dual_frames == 100);
    std::cout << "PASS persistent: 100 frames, adaptive split bounded 25-50%, attachment "
                 "removal/resource replacement/dirty history\n";
}
std::vector<unsigned char> ReadFile(fs::path path) {
    std::ifstream f(path, std::ios::binary);
    CHECK(f.good());
    return {std::istreambuf_iterator<char>(f), {}};
}
struct Loader : spine::TextureLoader {
    void load(spine::AtlasPage &page, const spine::String &) override {
        page.width = 512;
        page.height = 512;
    }
    void unload(void *) override {}
};
std::vector<DrawablePtr> Pose(const fs::path &role, TexturePtr texture, float seconds,
                              bool filter = true, const std::string &animation = "idle") {
    Loader loader;
    auto atlas_bytes = ReadFile(role / "skeleton.atlas"), skel = ReadFile(role / "skeleton.skel");
    spine::Atlas atlas(reinterpret_cast<const char *>(atlas_bytes.data()), atlas_bytes.size(), "",
                       &loader);
    spine::SkeletonBinary reader(&atlas);
    std::unique_ptr<spine::SkeletonData> data(reader.readSkeletonData(skel.data(), skel.size()));
    if (!data)
        throw std::runtime_error(reader.getError().buffer());
    spine::Skeleton skeleton(data.get());
    skeleton.setToSetupPose();
    if (data->getSkins().size() > 1)
        skeleton.setSkin(data->getSkins()[1]);
    spine::AnimationStateData state_data(data.get());
    spine::AnimationState state(&state_data);
    CHECK(data->findAnimation(animation.c_str()));
    state.setAnimation(0, animation.c_str(), true);
    state.update(seconds);
    state.apply(skeleton);
    skeleton.update(seconds);
    skeleton.updateWorldTransform(spine::Physics_Update);
    std::vector<DrawablePtr> scene;
    float minx = 1e9f, maxx = -1e9f, miny = 1e9f, maxy = -1e9f;
    struct AttachmentMesh {
        std::vector<Vertex2> vertices;
        std::vector<uint16_t> indices;
    };
    std::vector<AttachmentMesh> meshes;
    auto &slots = skeleton.getDrawOrder();
    for (size_t n = 0; n < slots.size(); ++n) {
        auto *slot = slots[n];
        auto *attachment = slot->getAttachment();
        if (!attachment)
            continue;
        AttachmentMesh m;
        std::vector<float> xy;
        spine::Vector<float> *uv = nullptr;
        if (attachment->getRTTI().isExactly(spine::RegionAttachment::rtti)) {
            auto *r = static_cast<spine::RegionAttachment *>(attachment);
            xy.resize(8);
            r->computeWorldVertices(*slot, xy.data(), 0, 2);
            uv = &r->getUVs();
            m.indices = {0, 1, 2, 0, 2, 3};
        } else if (attachment->getRTTI().isExactly(spine::MeshAttachment::rtti)) {
            auto *r = static_cast<spine::MeshAttachment *>(attachment);
            xy.resize(r->getWorldVerticesLength());
            r->computeWorldVertices(*slot, xy.data());
            uv = &r->getUVs();
            auto &ids = r->getTriangles();
            m.indices.assign(ids.buffer(), ids.buffer() + ids.size());
        } else
            continue;
        for (size_t i = 0; i < xy.size() / 2; ++i) {
            Vertex2 v;
            v.x = xy[i * 2];
            v.y = xy[i * 2 + 1];
            v.u = (*uv)[i * 2];
            v.v = (*uv)[i * 2 + 1];
            m.vertices.push_back(v);
            minx = std::min(minx, v.x);
            maxx = std::max(maxx, v.x);
            miny = std::min(miny, v.y);
            maxy = std::max(maxy, v.y);
        }
        meshes.push_back(m);
    }
    CHECK(!meshes.empty());
    const float scale = std::min(270.f / (maxx - minx), 275.f / (maxy - miny));
    for (auto &mesh : meshes) {
        for (auto &v : mesh.vertices) {
            v.x = (v.x - (minx + maxx) / 2) * scale;
            v.y = (v.y - (miny + maxy) / 2) * scale;
        }
        scene.push_back(MeshDrawable(mesh.vertices, mesh.indices, texture, {160, 160}, {1, 1}, 0,
                                     Normal, filter));
    }
    return scene;
}
void TestRole(const fs::path &role, const fs::path &raw, const fs::path &out) {
    auto pixels = ReadFile(raw);
    CHECK(pixels.size() == 512 * 512 * 4);
    auto texture = Texture::create(512, 512, pixels.data(), false, 1, 1, nullptr, 32, true);
    Loader loader;
    auto atlas_bytes = ReadFile(role / "skeleton.atlas"), skel = ReadFile(role / "skeleton.skel");
    spine::Atlas atlas(reinterpret_cast<const char *>(atlas_bytes.data()), atlas_bytes.size(), "", &loader);
    spine::SkeletonBinary reader(&atlas);
    std::unique_ptr<spine::SkeletonData> data(reader.readSkeletonData(skel.data(), skel.size()));
    CHECK(data);
    for (size_t animation_index = 0; animation_index < data->getAnimations().size(); ++animation_index) {
        const std::string animation = data->getAnimations()[animation_index]->getName().buffer();
    for (bool filter : {false, true})
        for (float seconds : {0.f, .25f, 1.f, 2.5f, 4.75f, 5.99f}) {
            auto scene = Pose(role, texture, seconds, filter, animation);
            auto base = CaptureSavedBaseline(scene);
            auto same_pose = Pose(role, texture, seconds, filter, animation);
            Compare(base, Capture(HomeRenderMode::Baseline, same_pose),
                    "saved 75fbc1ba real role " + role.filename().string());
            auto previous = Pose(role, texture, seconds, filter, animation);
            Compare(base, CapturePrevious(previous), "saved 26cfcc19 " + animation);
            for (auto profile : {HomeRenderProfile::V1, HomeRenderProfile::V2}) {
            ConfigureHomeRenderOptions(profile, 30, true);
            for (auto mode :
                 {HomeRenderMode::Render, HomeRenderMode::Dual, HomeRenderMode::Combined}) {
                auto next = Pose(role, texture, seconds, filter, animation);
                Compare(base, Capture(mode, next),
                        role.filename().string() + " pose " + std::to_string(seconds) + " " +
                            HomeRenderModeName(mode));
            }
            }
            if (seconds == 0 || seconds == 2.5f) {
                std::ofstream f(out / ("frame_" + role.filename().string() + "_" +
                                       std::to_string(seconds) + ".rgb565"),
                                std::ios::binary);
                f.write(reinterpret_cast<const char *>(base.data()), base.size() * 2);
            }
        }
    }
    std::cout << "PASS real Spine 4.2 role " << role.filename().string()
              << ": all animations x 6 times x 2 filters x 2 profiles x 3 modes; saved 75fbc1ba/26cfcc19 (pixel exact)\n";
}
ImageData bridge_image{};
const ImageData &BridgeTexture(const char *) { return bridge_image; }
void TestSpineBridge(const fs::path &role,const fs::path &raw) {
    auto bytes=ReadFile(raw);
    Loader loader;
    auto atlas_bytes=ReadFile(role/"skeleton.atlas"), skel=ReadFile(role/"skeleton.skel");
    spine::Atlas atlas(reinterpret_cast<const char*>(atlas_bytes.data()),atlas_bytes.size(),"",&loader);
    spine::SkeletonBinary reader(&atlas);
    std::unique_ptr<spine::SkeletonData> data(reader.readSkeletonData(skel.data(),skel.size()));
    CHECK(data);
    CubicatTextureLoader::init(MEMORY,BridgeTexture);
    for (bool filter : {false,true}) {
        for (size_t motion=0;motion<data->getAnimations().size();++motion) {
            std::vector<std::vector<uint16_t>> saved;
            for (auto profile : {HomeRenderProfile::V1,HomeRenderProfile::V2}) {
                ConfigureHomeRenderOptions(profile,30,true);
                ConfigureHomeRenderMode(HomeRenderMode::Combined);
                auto node=SpineNode::create();
                bridge_image={512,512,1,1,false,true,0,
                    new Texture(512,512,bytes.data(),false,1,1,nullptr,32,true),nullptr,32};
                CHECK(node->loadWithBinaryFile((role/"skeleton.skel").string(),(role/"skeleton.atlas").string(),.3f));
                auto root=Node2D::create("bridge_root");
                node->setParent(root.get()); node->setPosition({160,160});
                node->useBilinearFilter(filter);
                CHECK(node->setAnimation(0,data->getAnimations()[motion]->getName().buffer(),true));
                Surface surface; Renderer renderer(&surface);
                float previous=0;
                unsigned frame=0;
                for(float time:{0.f,.25f,1.f,2.5f,4.75f,5.99f}) {
                    root->update(time-previous,false); previous=time;
                    std::vector<DrawablePtr> scene; root->findDrawables(scene);
                    renderer.renderObjects(scene); surface.Guards();
                    std::vector<uint16_t> pixels(surface.Data(),surface.Data()+320*320);
                    if(profile==HomeRenderProfile::V1) saved.push_back(pixels);
                    else Compare(saved[frame],pixels,"production SpineNode persistent mesh/texture "+
                                 role.filename().string());
                    ++frame;
                }
            }
        }
    }
    std::cout<<"PASS production SpineNode bridge "<<role.filename().string()
             <<": all animations x 2 filters x 6 sequential times, v1/v2 pixels exact\n";
}

struct Sink {
    std::atomic<unsigned> calls{0};
    std::atomic<bool> gate{false}, fail_next{false};
    std::vector<uint16_t> panel = std::vector<uint16_t>(320 * 320);
    std::vector<uint16_t> ids;
    std::vector<HomeFramePipeline::Frame> rects;
    static bool Transfer(void *ctx, const HomeFramePipeline::Frame &f, HomeLcdFramePerf &perf) {
        auto &self = *static_cast<Sink *>(ctx);
        const int64_t start = esp_timer_get_time();
        // Delay sampling: any early snapshot reuse would corrupt these values.
        while (self.gate.load())
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
        for (int y = f.y1; y < f.y2; ++y)
            for (int x = f.x1; x < f.x2; ++x) {
                const auto value = f.pixels[y * f.stride + x];
                if (value != f.pixels[f.y1 * f.stride + f.x1])
                    throw std::runtime_error("snapshot overwritten in transit");
                self.panel[y * 320 + x] = value;
            }
        self.ids.push_back(f.pixels[f.y1 * f.stride + f.x1]);
        self.rects.push_back(f);
        ++self.calls;
        perf.transfer_us = esp_timer_get_time() - start;
        perf.pixels = (f.x2 - f.x1) * (f.y2 - f.y1);
        perf.ok = !self.fail_next.exchange(false);
        return perf.ok;
    }
};
void TestPipeline() {
    TakeHomeLcdPerfWindow();
    ConfigureHomeRenderMode(HomeRenderMode::Combined);
    Sink sink;
    std::vector<uint16_t> source(320 * 320);
    {
        HomeFramePipeline pipeline(320, 320, Sink::Transfer, &sink);
        CHECK(pipeline.Initialize());
        CHECK(pipeline.Initialize());
        CHECK(!pipeline.Submit({nullptr, 320, 0, 0, 320, 320}, false, false));
        CHECK(!pipeline.Submit({source.data(), 320, -1, 0, 320, 320}, false, false));
        CHECK(!pipeline.Submit({source.data(), 319, 0, 0, 320, 320}, false, false));
        CHECK(!pipeline.Submit({source.data(), 320, 0, 0, 321, 320}, false, false));
        sink.gate.store(true);
        for (int i = 1; i <= 2; ++i) {
            std::fill(source.begin(), source.end(), i);
            CHECK(pipeline.Submit({source.data(), 320, 11, 13, 300, 308}, false, true));
        }
        CHECK(sink.calls == 0);
        auto before = TakeHomeLcdPerfWindow();
        CHECK(before.accepted == 2 && before.completed == 0);
        std::atomic<bool> third_accepted{false};
        std::fill(source.begin(), source.end(), 3);
        std::thread producer([&] {
            CHECK(pipeline.Submit({source.data(), 320, 11, 13, 300, 308}, false, true));
            third_accepted = true;
        });
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
        CHECK(!third_accepted);
        sink.gate = false;
        producer.join();
        for (int i = 4; i <= 103; ++i) {
            std::fill(source.begin(), source.end(), i);
            CHECK(pipeline.Submit({source.data(), 320, 11, 13, 300, 308}, i % 17 == 0, true));
            std::fill(source.begin(), source.end(), 0xdead);
        }
        pipeline.Drain();
        CHECK(sink.calls == 103);
        CHECK(sink.ids.size() == 103);
        for (unsigned i = 0; i < 103; ++i)
            CHECK(sink.ids[i] == i + 1);
        auto perf = TakeHomeLcdPerfWindow();
        CHECK(perf.completed == 103 && perf.accepted == 101 && perf.queue_blocks > 0 &&
              perf.failures == 0);
        CHECK(sink.panel[12 * 320 + 11] == 0 && sink.panel[13 * 320 + 11] == 103 &&
              sink.panel[307 * 320 + 299] == 103 && sink.panel[308 * 320 + 299] == 0);
        sink.fail_next = true;
        std::fill(source.begin(), source.end(), 104);
        CHECK(!pipeline.Submit({source.data(), 320, 20, 20, 60, 60}, true, true));
        CHECK(HomeLcdRecoveryRequested());
        std::fill(source.begin(), source.end(), 105);
        CHECK(pipeline.Submit({source.data(), 320, 20, 20, 60, 60}, false, true));
        CHECK(sink.panel[0] == 105 && sink.panel.back() == 105);
        CHECK(!GetHomeRenderStatus().pipeline_enabled);
        CHECK(!HomeLcdRecoveryRequested());
        auto failure = TakeHomeLcdPerfWindow();
        CHECK(failure.failures == 1 && failure.rejected == 1 && failure.completed == 1);
    }
    // Pause/drain/resume and destruction must wait for outstanding frames.
    for (int n = 0; n < 8; ++n) {
        HomeFramePipeline pipeline(320, 320, Sink::Transfer, &sink);
        CHECK(pipeline.Initialize());
        std::fill(source.begin(), source.end(), n + 200);
        CHECK(pipeline.Submit({source.data(), 320, 0, 0, 320, 320}, false, true));
        pipeline.Drain();
        CHECK(pipeline.Submit({source.data(), 320, 0, 0, 320, 320}, false, true));
    }
    HostFailHeap = true;
    {
        HomeFramePipeline p(320, 320, Sink::Transfer, &sink);
        CHECK(!p.Initialize());
    }
    HostFailTask = "home_lcd0";
    {
        HomeFramePipeline p(320, 320, Sink::Transfer, &sink);
        CHECK(!p.Initialize());
    }
    HostFailTask.clear();
    HostInternalFree = 18000;
    {
        HomeFramePipeline p(320, 320, Sink::Transfer, &sink);
        CHECK(!p.Initialize());
    }
    HostInternalFree = 512 * 1024;
    std::cout << "PASS pipeline: FIFO 103 frames, 2-slot backpressure, no overwrite, sync "
                 "completion, dirty-copy bounds, failure/full-frame recovery, "
                 "pause/resume/drain/destruction, buffer/task/headroom fallback\n";
}
struct MockStream : HomeLcdTransport {
    struct Pending { const uint16_t *data; std::vector<uint16_t> saved; HomePixelRect window; };
    std::vector<Pending> pending;
    std::vector<uint16_t> output;
    HomePixelRect window;
    // A simulated 320x480 controller: the board exposes rows 160..479.
    std::vector<uint16_t> gram = std::vector<uint16_t>(320 * 480, 0x55aa);
    std::vector<HomePixelRect> windows;
    bool addressed = false;
    int fail_begin_at = -1;
    int tokens = 2, begins = 0, queues = 0, completions = 0, max_pending = 0;
    int fail_queue = -1;
    bool fail_begin = false, fail_take = false, delay_wait = false;
    std::vector<int> commands;
    bool Begin(HomePixelRect rect) override {
        // esp_lcd's tx_param drains queued color transfers before CASET/RASET.
        if (addressed) while (!pending.empty()) CompleteOne();
        CHECK(pending.empty()); window = rect; windows.push_back(rect); ++begins;
        return !fail_begin && begins != fail_begin_at;
    }
    void CompleteOne() {
        CHECK(!pending.empty());
        auto &p = pending.front();
        CHECK(std::memcmp(p.data, p.saved.data(), p.saved.size() * 2) == 0);
        for (size_t i = 0; i < p.saved.size(); ++i) {
            const auto v = p.saved[i];
            const auto pixel = uint16_t((v << 8) | (v >> 8));
            output.push_back(pixel);
            if (addressed) {
                const HomeLcdWindowBytes wire(p.window, 0, 160);
                const int left = (wire.columns[0] << 8) | wire.columns[1];
                const int right = (wire.columns[2] << 8) | wire.columns[3];
                const int top = (wire.rows[0] << 8) | wire.rows[1];
                const int bottom = (wire.rows[2] << 8) | wire.rows[3];
                const int width = right - left + 1;
                CHECK(left >= 0 && right < 320 && top >= 160 && bottom < 480);
                CHECK(p.saved.size() == size_t(width * (bottom - top + 1)));
                gram[(top + int(i) / width) * 320 + left + int(i) % width] = pixel;
            }
        }
        pending.erase(pending.begin()); ++tokens; ++completions;
    }
    bool TakeSlot() override {
        if (fail_take) { fail_take = false; return false; }
        if (!tokens) CompleteOne();
        CHECK(tokens > 0); --tokens; return true;
    }
    void GiveSlot() override { ++tokens; }
    bool Queue(const uint16_t *data, size_t count, bool first) override {
        ++queues; commands.push_back(HomeLcdStreamCommand(first));
        if (queues == fail_queue) return false;
        if (addressed) CHECK(first && count == size_t(window.Pixels()));
        pending.push_back({data, {data, data + count}, window});
        max_pending = std::max(max_pending, int(pending.size()));
        return true;
    }
    bool WaitAll() override {
        if (delay_wait) { delay_wait = false; return false; }
        while (!pending.empty()) CompleteOne();
        CHECK(tokens == 2); tokens = 0; return true;
    }
    void ReleaseAll() override { CHECK(tokens == 0); tokens = 2; }
};
void TestStream() {
    std::vector<uint16_t> source(333 * 320);
    for (unsigned i = 0; i < source.size(); ++i) source[i] = uint16_t(i * 53 + 7);
    std::vector<uint16_t> a(320 * 16 + 2, 0xbeef), b(a);
    uint16_t *strips[] = {a.data() + 1, b.data() + 1};
    for (auto rect : {HomePixelRect{0,0,320,320}, {17,23,208,316}, {7,9,8,10}, {13,21,318,39}}) {
        MockStream io; HomeLcdFramePerf perf; uint8_t next = 0;
        CHECK(HomeTransferLcdStream(io,source.data(),333,rect,strips,next,16,perf));
        CHECK(io.begins == 1 && io.completions == (rect.y2 - rect.y1 + 15) / 16);
        CHECK(io.commands[0] == 0x2c);
        for (size_t i = 1; i < io.commands.size(); ++i) CHECK(io.commands[i] == -1);
        if (io.completions > 1) CHECK(io.max_pending == 2);
        std::vector<uint16_t> expected;
        for (int y=rect.y1;y<rect.y2;++y)
            expected.insert(expected.end(),source.begin()+y*333+rect.x1,source.begin()+y*333+rect.x2);
        Compare(expected,io.output,"continuous stream pixel byte order and stride");
        CHECK(perf.ok && perf.pixels == rect.Pixels());
        CHECK(a.front()==0xbeef && a.back()==0xbeef && b.front()==0xbeef && b.back()==0xbeef);
    }
    HomeLcdWindowBytes gap({3,7,319,310},0,80);
    CHECK(gap.columns[0]==0 && gap.columns[1]==3 && gap.columns[2]==1 && gap.columns[3]==62);
    CHECK(gap.rows[0]==0 && gap.rows[1]==87 && gap.rows[2]==1 && gap.rows[3]==133);
    for (int fault=0;fault<4;++fault) {
        MockStream io; HomeLcdFramePerf perf; uint8_t next=0;
        io.fail_begin=fault==0; io.fail_queue=fault==1?3:-1;
        io.fail_take=fault==2; io.delay_wait=fault==3;
        CHECK(!HomeTransferLcdStream(io,source.data(),333,{0,0,320,80},strips,next,16,perf));
        CHECK(io.pending.empty() && io.tokens==2 && !perf.ok);
    }
    std::cout<<"PASS LCD production stream: one window, RAMWR then data-only, 2 DMA slots overlap, "
                "odd width/stride/gap/last strip/byte order, command/queue/slot/completion failures drained\n";
}
void TestAddressedStream() {
    std::vector<uint16_t> source(333 * 320);
    for (size_t i = 0; i < source.size(); ++i) source[i] = uint16_t(i * 53 + 7);
    std::vector<uint16_t> a(320 * 16 + 2, 0xbeef), b(a);
    uint16_t *strips[] = {a.data() + 1, b.data() + 1};
    for (auto rect : {HomePixelRect{0,0,320,320}, {17,23,208,316}, {7,9,8,10}, {13,21,318,39}}) {
        MockStream io; io.addressed = true; HomeLcdFramePerf perf; uint8_t next = 0;
        CHECK(HomeTransferLcdStream(io,source.data(),333,rect,strips,next,16,perf,true));
        const int count = (rect.y2 - rect.y1 + 15) / 16;
        CHECK(io.begins == count && io.completions == count && io.tokens == 2);
        for (int i = 0; i < count; ++i) {
            const auto w = io.windows[i];
            CHECK(w.x1 == rect.x1 && w.x2 == rect.x2);
            CHECK(w.y1 == rect.y1 + 16 * i && w.y2 == std::min(rect.y2,w.y1 + 16));
            CHECK(io.commands[i] == 0x2c);
        }
        // All visible corners and partial updates use the same pixel mapping;
        // untouched controller memory must not be overwritten.
        for (int y = 0; y < 480; ++y) for (int x = 0; x < 320; ++x) {
            const bool inside = x >= rect.x1 && x < rect.x2 &&
                                y >= rect.y1 + 160 && y < rect.y2 + 160;
            CHECK(io.gram[y*320+x] == (inside ? source[(y-160)*333+x] : 0x55aa));
        }
        CHECK(a.front()==0xbeef && a.back()==0xbeef && b.front()==0xbeef && b.back()==0xbeef);
    }
    // Execute the production clock renderer, then the production strip loop.
    // Starting from a colored Home frame makes leftover strips observable.
    MockStream panel; panel.addressed = true;
    std::vector<uint16_t> clock(320*320);
    uint8_t next = 0;
    for (int frame = 0; frame < 3; ++frame) {
        StandbyClockText text;
        text.valid = true;
        std::strcpy(text.time, frame == 2 ? "00:00" : "23:59");
        std::strcpy(text.date, frame == 2 ? "2026.10.07" : "2026.10.06");
        if (frame == 0) std::fill(clock.begin(),clock.end(),uint16_t{0x1f3f});
        else DrawStandbyClock(clock.data(),320,320,text);
        if (frame) CHECK(std::count(clock.begin(),clock.end(),uint16_t{0xffff}) > 3000);
        HomeLcdFramePerf perf;
        CHECK(HomeTransferLcdStream(panel,clock.data(),320,{0,0,320,320},strips,next,16,perf,true));
        Compare(clock,{panel.gram.begin()+160*320,panel.gram.end()},"Home/clock/midnight controller pixels");
    }
    for (int fault = 0; fault < 5; ++fault) {
        MockStream io; io.addressed = true; HomeLcdFramePerf perf; next = 0;
        io.fail_begin = fault == 0;
        io.fail_queue = fault == 1 ? 3 : -1;
        io.fail_take = fault == 2;
        io.delay_wait = fault == 3;
        io.fail_begin_at = fault == 4 ? 3 : -1;
        CHECK(!HomeTransferLcdStream(io,source.data(),333,{0,0,320,80},strips,next,16,perf,true));
        CHECK(io.pending.empty() && io.tokens == 2 && !perf.ok);
    }
    std::cout << "PASS LCD addressed strips: RAMWR/window for every segment, 160-row board gap, "
                 "full Home/clock/midnight pixels, untouched GRAM, corners/stride/short strip, "
                 "DMA lifetime and failures drained\n";
}
void TestMeshReuse() {
    auto mesh=Mesh2D::create(nullptr,0,nullptr,0,true);
    float xy[]={0,0, 0,20, 20,20, 20,0}, uv[]={0,1, 0,0, 1,0, 1,1};
    uint16_t ids[]={0,1,2,0,2,3};
    mesh->updateVertices(xy,4);
    CHECK(mesh->updateIndicesIfChanged(ids,6)); CHECK(mesh->updateUVsIfChanged(uv,8));
    CHECK(!mesh->updateIndicesIfChanged(ids,6)); CHECK(!mesh->updateUVsIfChanged(uv,8));
    xy[0]=1; mesh->updateVertices(xy,4);
    CHECK(!mesh->updateUVsIfChanged(uv,8));
    // Sequence UV and topology mutations at the SAME source address must invalidate.
    uv[0]=.25f; ids[0]=3;
    CHECK(mesh->updateUVsIfChanged(uv,8)); CHECK(mesh->updateIndicesIfChanged(ids,6));
    CHECK(mesh->getVertex(0)->u==.25f);
    float larger_xy[12]={},larger_uv[12]={}; mesh->updateVertices(larger_xy,6);
    CHECK(mesh->updateUVsIfChanged(larger_uv,12));
    CHECK(!mesh->updateUVsIfChanged(larger_uv,12));
    std::cout<<"PASS mesh reuse: unchanged data skips writes, same-pointer UV/topology mutation, "
                "new vertex allocation/attachment size invalidates cache\n";
}
struct DeltaSink {
    std::vector<uint16_t> panel=std::vector<uint16_t>(320*320);
    std::atomic<bool> gate{false}, entered{false}, fail{false};
    unsigned calls=0;
    HomePixelRect last;
    static bool Transfer(void *ctx,const HomeFramePipeline::Frame &f,HomeLcdFramePerf &perf) {
        auto &s=*static_cast<DeltaSink*>(ctx); s.entered=true;
        while(s.gate.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        for(int y=f.y1;y<f.y2;++y) for(int x=f.x1;x<f.x2;++x) s.panel[y*320+x]=f.pixels[y*f.stride+x];
        ++s.calls; s.last={f.x1,f.y1,f.x2,f.y2};
        perf.pixels=s.last.Pixels(); perf.ok=!s.fail.exchange(false); return perf.ok;
    }
};
void TestDeltaPipeline() {
    ConfigureHomeRenderMode(HomeRenderMode::Combined);
    ConfigureHomeRenderOptions(HomeRenderProfile::V2,30,true);
    ClearHomeLcdRecovery(); TakeHomeLcdPerfWindow();
    DeltaSink sink; std::vector<uint16_t> frame(320*320);
    {
        HomeFramePipeline p(320,320,DeltaSink::Transfer,&sink); CHECK(p.Initialize());
        // A delayed first transfer plus an unchanged successor verifies FIFO no-DMA jobs.
        sink.gate=true;
        CHECK(p.Submit({frame.data(),320,0,0,320,320},false,true));
        CHECK(p.Submit({frame.data(),320,0,0,320,320},false,true));
        CHECK(sink.calls==0);
        sink.gate=false; p.Drain();
        auto stats=TakeHomeLcdPerfWindow();
        CHECK(sink.calls==1 && stats.completed==1 && stats.unchanged==1);
        // Drain invalidates the baseline; establish it, then test alternating/same-slot reuse.
        CHECK(p.Submit({frame.data(),320,0,0,320,320},false,true));
        for(int i=0;i<90;++i) {
            int x=10+i%40,y=13+i%50; frame[y*320+x]=uint16_t(i+1);
            CHECK(p.Submit({frame.data(),320,0,0,320,320},false,true));
        }
        p.Drain();
        Compare(frame,sink.panel,"90 ordered deltas with snapshot backpressure");
        CHECK(sink.last.Pixels()==1);
        // Outside the previous original valid rectangle must be treated as unknown.
        CHECK(p.Submit({frame.data(),320,100,100,110,110},true,true));
        CHECK(p.Submit({frame.data(),320,100,100,110,110},false,true));
        CHECK(p.Submit({frame.data(),320,99,100,111,110},false,true));
        p.Drain(); CHECK(sink.last.x1==99 && sink.last.x2==111);
        // Earlier failed frame invalidates an already queued unchanged delta.
        sink.entered=false; sink.gate=true; sink.fail=true;
        frame[0]=123; CHECK(p.Submit({frame.data(),320,0,0,320,320},false,true));
        while(!sink.entered.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
        CHECK(p.Submit({frame.data(),320,0,0,320,320},false,true));
        sink.gate=false; p.Drain();
        CHECK(HomeLcdRecoveryRequested());
        frame[319]=456;
        CHECK(p.Submit({frame.data(),320,0,0,1,1},false,true));
        CHECK(!HomeLcdRecoveryRequested()); CHECK(sink.last.Pixels()==320*320);
        Compare(frame,sink.panel,"failed predecessor/stale delta/full synchronous recovery");
    }
    auto stats=TakeHomeLcdPerfWindow(); CHECK(stats.failures==2);
    std::cout<<"PASS pixel diff: unchanged excluded from DMA FPS, 90 exact deltas, valid window expansion, "
                "FIFO failure invalidation, full synchronous recovery, no additional framebuffer\n";
}

void TestRenderOptions() {
    ConfigureHomeRenderMode(HomeRenderMode::Combined);
    ConfigureHomeRenderOptions(HomeRenderProfile::V1,40,true);
    CHECK(HomeLcdSpiMHz()==40 && !HomeV2Drawing() &&
          !HomeV2TransmissionRequested() && !HomePixelDiffRequested());
    ConfigureHomeRenderOptions(HomeRenderProfile::V2,30,true);
    ConfigureHomeRenderMode(HomeRenderMode::Render);
    CHECK(HomeV2Drawing() && !HomeV2TransmissionRequested() && !HomePixelDiffRequested());
    ConfigureHomeRenderMode(HomeRenderMode::Pipeline);
    CHECK(HomeV2Drawing() && HomeV2TransmissionRequested() && HomePixelDiffRequested());
    ConfigureHomeRenderOptions(HomeRenderProfile::V2,40,false);
    CHECK(HomeLcdSpiMHz()==40 && HomeV2TransmissionRequested() && !HomePixelDiffRequested());
    ConfigureHomeRenderMode(HomeRenderMode::Baseline);
    CHECK(HomeLcdSpiMHz()==30 && !HomeV2Drawing() && !HomeV2TransmissionRequested());
    ConfigureHomeRenderOptions(HomeRenderProfile::V2,30,true);
    std::cout<<"PASS options: v1/v2, drawing-only/transmission modes, pixel diff switch, "
                "40 MHz experiment and original baseline forced 30 MHz\n";
}

int main(int argc, char **argv) {
    std::cout.setf(std::ios::unitbuf);
    try {
        CHECK(argc >= 2);
        // Production SpineNode owns a static texture loader. Its base destructor
        // runs after main: the allocator fixture must also have process lifetime.
        auto *extension = new spine::DefaultSpineExtension;
        spine::SpineExtension::setInstance(extension);
        TestRenderOptions();
        TestSynthetic();
        TestPersistent();
        ConfigureHomeRenderOptions(HomeRenderProfile::V1,30,false);
        TestPipeline();
        TestStream();
        TestAddressedStream();
        TestMeshReuse();
        TestDeltaPipeline();
        for (int i = 2; i + 1 < argc; i += 2) {
            TestRole(argv[i], argv[i + 1], argv[1]);
            TestSpineBridge(argv[i], argv[i + 1]);
        }
        HostJoinTasks();
        std::cout << "ALL HOME RENDER HOST TESTS PASSED\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << "\n";
        std::_Exit(1);
    }
}
