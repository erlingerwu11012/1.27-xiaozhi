// Read-only metrics from the same Spine 4.2 runtime used by firmware.
#include <spine/spine.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <set>
#include <vector>
#include <stdexcept>
#include <algorithm>
#include <cmath>
namespace fs=std::filesystem;
std::vector<unsigned char> read(const fs::path& p){std::ifstream f(p,std::ios::binary);if(!f)throw std::runtime_error("read failed");return {std::istreambuf_iterator<char>(f),{}};}
struct Loader:spine::TextureLoader{void load(spine::AtlasPage& p,const spine::String&)override{p.width=512;p.height=512;}void unload(void*)override{}};
struct Count {
 size_t meshes=0,regions=0,vertices=0,triangles=0;
 void add(spine::Attachment* a){
  if(!a)return;
  if(a->getRTTI().isExactly(spine::MeshAttachment::rtti)){
   auto* m=static_cast<spine::MeshAttachment*>(a);++meshes;vertices+=m->getWorldVerticesLength()/2;triangles+=m->getTriangles().size()/3;
  }else if(a->getRTTI().isExactly(spine::RegionAttachment::rtti)){++regions;vertices+=4;triangles+=2;}
 }
 void print(std::ostream& o)const{o<<"{\"meshes\":"<<meshes<<",\"regions\":"<<regions<<",\"vertices\":"<<vertices<<",\"triangles\":"<<triangles<<'}';}
 void low(const Count& c){meshes=std::min(meshes,c.meshes);regions=std::min(regions,c.regions);vertices=std::min(vertices,c.vertices);triangles=std::min(triangles,c.triangles);}
 void high(const Count& c){meshes=std::max(meshes,c.meshes);regions=std::max(regions,c.regions);vertices=std::max(vertices,c.vertices);triangles=std::max(triangles,c.triangles);}
};
bool drawable(spine::Slot* s){
 auto* a=s->getAttachment();if(!a||!s->getBone().isActive()||s->getColor().a==0)return false;
 if(a->getRTTI().isExactly(spine::MeshAttachment::rtti)){auto*m=static_cast<spine::MeshAttachment*>(a);return m->getRegion()&&m->getColor().a!=0;}
 if(a->getRTTI().isExactly(spine::RegionAttachment::rtti)){auto*m=static_cast<spine::RegionAttachment*>(a);return m->getRegion()&&m->getColor().a!=0;}
 return false;
}
int main(int argc,char** argv){try{
 if(argc!=3)throw std::runtime_error("metrics ASSET_DIR REPORT.json");
 spine::SpineExtension::setInstance(new spine::DefaultSpineExtension);
 Loader loader;fs::path dir=argv[1];auto a=read(dir/"skeleton.atlas"),b=read(dir/"skeleton.skel");
 spine::Atlas atlas(reinterpret_cast<const char*>(a.data()),a.size(),"",&loader);
 spine::SkeletonBinary parser(&atlas);std::unique_ptr<spine::SkeletonData>d(parser.readSkeletonData(b.data(),b.size()));
 if(!d)throw std::runtime_error(parser.getError().buffer());
 Count resident;std::set<spine::Attachment*> seen;
 for(size_t i=0;i<d->getSkins().size();++i){auto entries=d->getSkins()[i]->getAttachments();while(entries.hasNext()){auto*att=entries.next()._attachment;if(seen.insert(att).second)resident.add(att);}}
 std::ofstream out(argv[2]);
 out<<"{\"runtime\":\""<<d->getVersion().buffer()<<"\",\"bones\":"<<d->getBones().size()<<",\"slots\":"<<d->getSlots().size()<<",\"physics_constraints\":"<<d->getPhysicsConstraints().size()<<",\"resident_geometry\":";resident.print(out);out<<",\"animations\":[";
 for(size_t i=0;i<d->getAnimations().size();++i){auto*anim=d->getAnimations()[i];size_t frames=0;
  for(size_t j=0;j<anim->getTimelines().size();++j)frames+=anim->getTimelines()[j]->getFrameCount();
  Count lo{size_t(-1),size_t(-1),size_t(-1),size_t(-1)},hi;
  size_t boneLo=size_t(-1),boneHi=0,physicsLo=size_t(-1),physicsHi=0,mixedLo=size_t(-1),mixedHi=0;std::set<size_t> visibleSlots;
  for(int fps:{5,10,24,30,60,240}){
   spine::Skeleton sk(d.get());sk.setSkin(d->getDefaultSkin());sk.setToSetupPose();spine::AnimationStateData sd(d.get());spine::AnimationState state(&sd);state.setAnimation(0,anim,true);
   std::set<float> times{0,anim->getDuration()*3};for(int k=0;k<=int(std::ceil(anim->getDuration()*3*fps));++k)times.insert(k/float(fps));
   if(fps==240)for(size_t j=0;j<anim->getTimelines().size();++j){auto*t=anim->getTimelines()[j];auto&f=t->getFrames();for(size_t k=0;k<f.size();k+=t->getFrameEntries())if(f[k]>=0&&f[k]<=anim->getDuration())for(int loop=0;loop<3;++loop)times.insert(f[k]+loop*anim->getDuration());}
   float last=0;for(float time:times){state.update(time-last);state.apply(sk);sk.update(time-last);sk.updateWorldTransform(spine::Physics_Update);last=time;
    Count visible;for(size_t j=0;j<sk.getSlots().size();++j)if(drawable(sk.getSlots()[j])){visible.add(sk.getSlots()[j]->getAttachment());visibleSlots.insert(j);}lo.low(visible);hi.high(visible);
    size_t nb=0,np=0,nm=0;for(size_t j=0;j<sk.getBones().size();++j)if(sk.getBones()[j]->isActive())++nb;
    for(size_t j=0;j<sk.getPhysicsConstraints().size();++j){auto*p=sk.getPhysicsConstraints()[j];if(p->isActive()){++np;if(p->getMix()!=0)++nm;}}
    boneLo=std::min(nb,boneLo);boneHi=std::max(nb,boneHi);physicsLo=std::min(np,physicsLo);physicsHi=std::max(np,physicsHi);mixedLo=std::min(nm,mixedLo);mixedHi=std::max(nm,mixedHi);
   }
  }
  if(i)out<<',';out<<"{\"name\":\""<<anim->getName().buffer()<<"\",\"duration_seconds\":"<<anim->getDuration()<<",\"timelines\":"<<anim->getTimelines().size()<<",\"timeline_keyframes\":"<<frames<<",\"visible_min\":";lo.print(out);out<<",\"visible_max\":";hi.print(out);
  out<<",\"active_bones\":["<<boneLo<<','<<boneHi<<"],\"active_physics\":["<<physicsLo<<','<<physicsHi<<"],\"nonzero_mix_physics\":["<<mixedLo<<','<<mixedHi<<"],\"visible_slot_union\":"<<visibleSlots.size()<<'}';
 }
 out<<"]}\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
