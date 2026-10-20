#include <spine/spine.h>
#include "tts_overlay_attachment.h"
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <vector>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define LOGE(...) ((void)0)
static const char* kTag="test";
int64_t esp_timer_get_time() { return 1000000; }
namespace spine { SpineExtension* getDefaultExtension() { return new DefaultSpineExtension; } }
struct Loader:spine::TextureLoader {
    void load(spine::AtlasPage& page,const spine::String&) override { page.texture=reinterpret_cast<void*>(1); }
    void unload(void*) override {}
};
struct Bridge {
    spine::Skeleton* m_pSkeleton;
    spine::AnimationState* m_pAnimState;
    spine::TrackEntry* setAnimation(int,const std::string&,bool);
    void clearTrack(int);
};
// @BRIDGE
struct Subtitle { void setVisible(bool) {} };
struct Player {
    Bridge* spine;
    Subtitle* subtitle=nullptr;
    bool tts_playback_active=false,tts_animation_present_pending=false;
    std::string current_state="idle";
    bool HasSpineAnimation(const char* name) { return has_talk && spine->m_pSkeleton->getData()->findAnimation(name)!=nullptr; }
    void UpdateDialogueVisibility(uint32_t) {}
    const char* NetworkIconName(int) { return "connected"; }
    int network_state=0;bool muted_state=false;
    bool has_talk=true;
    void ApplyState(const std::string&,uint32_t);
    void ApplyTtsPlayback(bool);
};
// @PLAYER
std::vector<unsigned char> read(const std::string& path) {
    std::ifstream f(path,std::ios::binary);assert(f.good());
    return std::vector<unsigned char>(std::istreambuf_iterator<char>(f),{});
}
struct Pose {
    std::vector<float> bones;
    std::vector<std::string> attachments;
};
Pose pose(spine::Skeleton& skel) {
    Pose p;
    for(size_t i=0;i<skel.getBones().size();++i) {
        auto* b=skel.getBones()[i];
        for(float v:{b->getX(),b->getY(),b->getRotation(),b->getScaleX(),b->getScaleY(),b->getShearX(),b->getShearY()})p.bones.push_back(v);
    }
    for(size_t i=0;i<skel.getSlots().size();++i) {
        auto* a=skel.getSlots()[i]->getAttachment();p.attachments.emplace_back(a?a->getName().buffer():"");
    }
    return p;
}
bool same(const Pose& a,const Pose& b) {
    if(a.attachments!=b.attachments || a.bones.size()!=b.bones.size())return false;
    for(size_t i=0;i<a.bones.size();++i)if(std::fabs(a.bones[i]-b.bones[i])>0.0002)return false;
    return true;
}
int main(int argc,char**argv) {
    spine::SpineExtension::setInstance(new spine::DefaultSpineExtension);
    assert(argc==2);std::string root=argv[1];Loader loader;
    auto atlas_data=read(root+"/skeleton.atlas"),skel_data=read(root+"/skeleton.skel");
    spine::Atlas atlas(reinterpret_cast<const char*>(atlas_data.data()),atlas_data.size(),"",&loader);
    spine::SkeletonBinary reader(&atlas);
    std::unique_ptr<spine::SkeletonData> data(reader.readSkeletonData(skel_data.data(),skel_data.size()));
    assert(data && data->findAnimation("idle") && data->findAnimation("talk_start"));
    spine::Skeleton skel(data.get()),reference(data.get());
    {
        spine::AnimationStateData before_settings(data.get());
        spine::AnimationState before(&before_settings);
        before.setAnimation(0,"idle",true);before.setAnimation(1,"talk_start",true);
        before.update(.1f);before.apply(skel);
        assert(skel.findSlot("zuiba1")->getAttachment()->getName()==spine::String("zui2"));
        std::cout<<"REPRODUCED: idle overrides talk_start setup mouth with zui2\n";
    }
    skel.setToSetupPose();
    assert(cubicat::PrepareTtsOverlayAttachment(skel,"talk_start","zuiba1"));
    auto* prepared=data->findAnimation("talk_start");
    assert(cubicat::PrepareTtsOverlayAttachment(skel,"talk_start","zuiba1"));
    assert(prepared==data->findAnimation("talk_start"));
    assert(!cubicat::PrepareTtsOverlayAttachment(skel,"missing","zuiba1"));
    assert(!cubicat::PrepareTtsOverlayAttachment(skel,"talk_start","missing"));
    auto* authored_idle=data->findAnimation("idle");
    assert(cubicat::PrepareTtsOverlayAttachment(skel,"idle","zuiba1"));
    assert(authored_idle==data->findAnimation("idle"));
    spine::AnimationStateData settings(data.get());
    spine::AnimationState state(&settings),ref_state(&settings);
    Bridge bridge{&skel,&state};Player player{&bridge};
    state.setAnimation(0,"idle",true);ref_state.setAnimation(0,"idle",true);
    player.ApplyTtsPlayback(true);assert(state.getCurrent(1)!=nullptr);
    bool moved=false;float min_mouth_scale=100,max_mouth_scale=0;
    for(int i=0;i<120;++i) {
        const float dt=i<40?1.f/60:(i%2?.19f:.23f); // Also exercise physical 5 fps cadence.
        state.update(dt);state.apply(skel);
        ref_state.update(dt);ref_state.apply(reference);
        skel.update(dt);skel.updateWorldTransform(spine::Physics_Update);
        reference.update(dt);reference.updateWorldTransform(spine::Physics_Update);
        auto* mouth=skel.findSlot("zuiba1");
        assert(mouth->getAttachment()->getName()==spine::String("zuiba1"));
        assert(reference.findSlot("zuiba1")->getAttachment()->getName()==spine::String("zui2"));
        min_mouth_scale=std::min(min_mouth_scale,mouth->getBone().getScaleY());
        max_mouth_scale=std::max(max_mouth_scale,mouth->getBone().getScaleY());
        moved=moved||!same(pose(skel),pose(reference));
    }
    assert(moved && min_mouth_scale<.65f && max_mouth_scale>1.f);
    for(const char* home:{"listening","thinking","reminder","idle"}) {
        player.ApplyState(home,0);
        assert(state.getCurrent(1) && state.getCurrent(1)->getAnimation()->getName()==spine::String("talk_start"));
    }
    // Synchronize only the reference idle phase: changing home may rearm track 0.
    ref_state.getCurrent(0)->setTrackTime(state.getCurrent(0)->getTrackTime());
    player.ApplyTtsPlayback(false);
    for(int i=0;i<3;++i) {
        state.update(1.f/60);state.apply(skel);
        ref_state.update(1.f/60);ref_state.apply(reference);
    }
    assert(!player.tts_playback_active && same(pose(skel),pose(reference)));
    assert(skel.findSlot("zuiba1")->getAttachment()->getName()==spine::String("zui2"));
    player.ApplyTtsPlayback(true);assert(player.tts_playback_active);
    player.ApplyTtsPlayback(false);
    player.has_talk=false;
    player.ApplyTtsPlayback(true);assert(!player.tts_playback_active);
    std::cout<<"PASS: nvhai_builtin correct mouth attachment over idle, animated pose, home-state independence, empty-track idle restoration and resume\n";
}
