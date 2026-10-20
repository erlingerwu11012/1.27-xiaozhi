// Offline asset layout tool: Spine 4.2 bounds and production-renderer previews.
#include "graphic_engine/renderer/renderer.h"
#include "spine_node.h"
#include <spine/spine.h>
#include "utils/home_render_options.h"
#include "host_runtime.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <vector>
namespace fs = std::filesystem;
struct Bounds {
    float x1=1e30f,y1=1e30f,x2=-1e30f,y2=-1e30f;
    void Add(float x,float y) {
        if (!std::isfinite(x)||!std::isfinite(y)) throw std::runtime_error("non-finite vertex");
        x1=std::min(x1,x); y1=std::min(y1,y); x2=std::max(x2,x); y2=std::max(y2,y);
    }
    void Merge(const Bounds& b) { if(b.x2>=b.x1){Add(b.x1,b.y1);Add(b.x2,b.y2);} }
    void Print(std::ostream& f) const { f<<'['<<x1<<','<<y1<<','<<x2<<','<<y2<<']'; }
};
std::vector<unsigned char> Read(const fs::path& p) {
    std::ifstream f(p,std::ios::binary);
    if(!f) throw std::runtime_error("cannot read "+p.string());
    return {std::istreambuf_iterator<char>(f),{}};
}
struct Loader:spine::TextureLoader {
    void load(spine::AtlasPage& page,const spine::String&) override {
        if(page.width<=0 || page.height<=0) throw std::runtime_error("atlas page size missing");
    }
    void unload(void*) override {}
};
Bounds Geometry(spine::Skeleton& sk, std::map<std::string,Bounds>* attachments=nullptr) {
    Bounds total;
    auto& slots=sk.getDrawOrder();
    for(size_t i=0;i<slots.size();++i) {
        auto* s=slots[i]; auto* a=s->getAttachment();
        if(!a || !s->getBone().isActive() || s->getColor().a==0) continue;
        std::vector<float> vertices;
        if(a->getRTTI().isExactly(spine::RegionAttachment::rtti)) {
            auto* r=static_cast<spine::RegionAttachment*>(a);
            if(!r->getRegion() || r->getColor().a==0) continue;
            vertices.resize(8); r->computeWorldVertices(*s,vertices.data(),0,2);
        } else if(a->getRTTI().isExactly(spine::MeshAttachment::rtti)) {
            auto* r=static_cast<spine::MeshAttachment*>(a);
            if(!r->getRegion() || r->getColor().a==0) continue;
            vertices.resize(r->getWorldVerticesLength());r->computeWorldVertices(*s,vertices.data());
        } else continue;
        Bounds b;
        for(size_t n=0;n<vertices.size();n+=2) b.Add(vertices[n],vertices[n+1]);
        total.Merge(b);
        if(attachments) (*attachments)[s->getData().getName().buffer()].Merge(b);
    }
    return total;
}
void Scan(const fs::path& dir,float scale,const fs::path& out,bool idleOverlay=false) {
    Loader loader; auto a=Read(dir/"skeleton.atlas"), b=Read(dir/"skeleton.skel");
    spine::Atlas atlas(reinterpret_cast<const char*>(a.data()),a.size(),"",&loader);
    spine::SkeletonBinary reader(&atlas);reader.setScale(scale);
    std::unique_ptr<spine::SkeletonData> data(reader.readSkeletonData(b.data(),b.size()));
    if(!data) throw std::runtime_error(reader.getError().buffer());
    std::ofstream f(out);f<<std::setprecision(10);
    f<<"{\"runtime\":\""<<data->getVersion().buffer()<<"\",\"scale\":"<<scale
     <<",\"bones\":"<<data->getBones().size()<<",\"physics\":"<<data->getPhysicsConstraints().size()
     <<",\"root\":["<<data->getBones()[0]->getX()<<','<<data->getBones()[0]->getY()<<"],\"skins\":[";
    for(size_t i=0;i<data->getSkins().size();++i){if(i)f<<',';f<<'"'<<data->getSkins()[i]->getName().buffer()<<'"';}
    f<<"],\"animations\":[";
    Bounds all;std::map<std::string,Bounds> attachments;
    for(size_t i=0;i<data->getAnimations().size();++i) {
        auto* anim=data->getAnimations()[i];
        Bounds motion;size_t samples=0;
        for(int fps:{5,10,24,30,60,240}) {
            spine::Skeleton sk(data.get());sk.setSkin(data->getDefaultSkin());sk.setToSetupPose();
            spine::AnimationStateData sd(data.get());spine::AnimationState state(&sd);
            if(idleOverlay && std::string(anim->getName().buffer())!="idle" && data->findAnimation("idle")) {
                state.setAnimation(0,"idle",true);state.setAnimation(1,anim,true);
            } else state.setAnimation(0,anim,true);
            std::set<float> times{0,anim->getDuration()*3};
            for(int k=0;k<=int(std::ceil(anim->getDuration()*3*fps));++k) times.insert(k/float(fps));
            if(fps==240) for(size_t n=0;n<anim->getTimelines().size();++n) {
                auto* tl=anim->getTimelines()[n];auto& frames=tl->getFrames();auto step=tl->getFrameEntries();
                for(size_t k=0;k<frames.size();k+=step) if(frames[k]>=0&&frames[k]<=anim->getDuration())
                    for(int loop=0;loop<3;++loop) times.insert(frames[k]+anim->getDuration()*loop);
            }
            float last=0;
            for(float t:times) {
                state.update(t-last);state.apply(sk);sk.update(t-last);
                sk.updateWorldTransform(spine::Physics_Update);
                motion.Merge(Geometry(sk,&attachments));last=t;++samples;
            }
        }
        all.Merge(motion);
        if(i)f<<',';
        f<<"{\"name\":\""<<anim->getName().buffer()<<"\",\"duration\":"<<anim->getDuration()<<",\"samples\":"<<samples<<",\"bounds\":";
        motion.Print(f);f<<'}';
    }
    f<<"],\"bounds\":";all.Print(f);f<<",\"attachments\":{";
    bool first=true;for(auto& entry:attachments){if(!first)f<<',';first=false;f<<'"'<<entry.first<<"\":";entry.second.Print(f);}
    f<<"}}\n";
}
ImageData image{};
const ImageData& Image(const char*){return image;}
struct Surface:cubicat::DisplayInterface,cubicat::DrawStageListener {
    std::vector<uint16_t> pixels=std::vector<uint16_t>(320*320,0x2124);
    Region dirty;
    cubicat::RenderBuffer getRenderBuffer() override {return {pixels.data(),320,320};}
    uint16_t getBackgroundColor() override {return 0x2124;}
    void onDrawStart(const Region&) override {}
    void onDrawFinish(const Region& r) override {dirty=r;}
};
void Preview(const fs::path& dir,float scale,const fs::path& rgba,const fs::path& out,const std::string& motion,bool bilinear=false,bool idleOverlay=false) {
    const auto png=Read(dir/"texture.png");
    if(png.size()<24 || png[0]!=137 || png[1]!='P' || png[2]!='N' || png[3]!='G')
        throw std::runtime_error("PNG header");
    auto dimension=[&](size_t i) {return (uint32_t(png[i])<<24)|(uint32_t(png[i+1])<<16)|(uint32_t(png[i+2])<<8)|uint32_t(png[i+3]);};
    const auto width=dimension(16),height=dimension(20);
    if(!width || !height || width>8192 || height>8192) throw std::runtime_error("PNG dimensions");
    auto bytes=Read(rgba);if(bytes.size()!=size_t(width)*height*4)throw std::runtime_error("RGBA size");
    cubicat::ConfigureHomeRenderOptions(cubicat::HomeRenderProfile::V2,30,true);
    cubicat::ConfigureHomeRenderMode(cubicat::HomeRenderMode::Render);
    CubicatTextureLoader::init(MEMORY,Image);
    image={uint16_t(width),uint16_t(height),1,1,false,true,0,new cubicat::Texture(width,height,bytes.data(),false,1,1,nullptr,32,true),nullptr,32};
    auto node=SpineNode::create();
    if(!node->loadWithBinaryFile((dir/"skeleton.skel").string(),(dir/"skeleton.atlas").string(),scale))throw std::runtime_error("load failed");
    node->setSkinByName("default");node->useBilinearFilter(bilinear);
    auto root=cubicat::Node2D::create("layout_root");node->setParent(root.get());node->setPosition({160,0});
    if(idleOverlay && motion!="idle") {
        if(!node->setAnimation(0,"idle",true) || !node->setAnimation(1,motion,true)) throw std::runtime_error("animation missing");
    } else if(!node->setAnimation(0,motion,true)) throw std::runtime_error("animation missing");
    Surface surface;cubicat::Renderer renderer(&surface);renderer.addDrawStageListener(&surface);
    fs::create_directories(out);
    std::ofstream windows(out/"regions.csv");windows<<"time,x,y,w,h,pixels\n";
    float previous=0;
    int vx1=320,vy1=320,vx2=-1,vy2=-1;
    for(int frame=0;frame<=420;++frame) {
        const float time=frame/30.f;root->update(time-previous,false);previous=time;
        std::vector<cubicat::DrawablePtr> scene;root->findDrawables(scene);renderer.renderObjects(scene);
        auto r=surface.dirty;windows<<time<<','<<r.x<<','<<r.y<<','<<r.w<<','<<r.h<<','<<r.w*r.h<<'\n';
        for(int y=0;y<320;++y) for(int x=0;x<320;++x) {
            if(surface.pixels[y*320+x]!=0x2124) {
                vx1=std::min(vx1,x);vy1=std::min(vy1,y);
                vx2=std::max(vx2,x);vy2=std::max(vy2,y);
            }
        }
        if(frame%30==0) {
            std::ofstream f(out/(motion+"_"+std::to_string(frame/30)+".rgb565"),std::ios::binary);
            f.write(reinterpret_cast<char*>(surface.pixels.data()),surface.pixels.size()*2);
        }
    }
    std::ofstream visible(out/"visible-bounds.json");
    visible<<"{\"bounds\":["<<vx1<<','<<vy1<<','<<vx2<<','<<vy2<<"],\"frames\":421,\"hz\":30}";
}
int main(int argc,char** argv) {
    try {
        spine::SpineExtension::setInstance(new spine::DefaultSpineExtension);
        if(argc<5)throw std::runtime_error("scan DIR SCALE REPORT | preview DIR SCALE RGBA OUT ANIMATION");
        if(std::string(argv[1])=="scan") Scan(argv[2],std::stof(argv[3]),argv[4],argc==6&&std::string(argv[5])=="overlay-idle");
        else if(std::string(argv[1])=="preview"&&(argc>=7&&argc<=9)) Preview(argv[2],std::stof(argv[3]),argv[4],argv[5],argv[6],argc>=8&&std::string(argv[7])=="bilinear",argc==9&&std::string(argv[8])=="overlay-idle");
        else throw std::runtime_error("invalid arguments");
        HostJoinTasks();return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';std::_Exit(1);}
}
