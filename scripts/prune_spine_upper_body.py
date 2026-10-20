"""Prune the reviewed hero_001 upper-body draft using its Spine 4.2 binary layout.

Preserves retained setup values and timeline payloads byte-for-byte. Bone and
constraint indices are remapped, constraint order is made contiguous, and
hidden-slot attachments/timelines are removed. Empty slots remain as detached
root slots so existing draw-order offsets preserve upper-body layering.
Unsupported binary features abort instead of guessing. No OTA bundle is made.
"""
from pathlib import Path
from dataclasses import dataclass
import json, struct, shutil, os, subprocess, hashlib
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'build/spine_role_layout/hero_001_upper_preview_20261002'
OUT=ROOT/'build/spine_role_layout/hero_001_upper_pruned_20261002'

def u(value):
    value &= 0xffffffff
    out=bytearray()
    while value>=128:out.append((value&127)|128);value>>=7
    out.append(value);return bytes(out)

@dataclass
class Record:
    start:int
    end:int
    refs:list
    name:str=''
    parent:int|None=None
    bone:int|None=None
    driven:tuple=()
    order:int|None=None
    def write(self,p,maps,override=None):
        out=bytearray();last=self.start;override=override or {}
        for start,end,kind,old in self.refs:
            value=override[(kind,old)] if (kind,old) in override else maps[kind][old]
            out+=p.data[last:start];out+=u(value);last=end
        out+=p.data[last:self.end];return bytes(out)

class Parser:
    def __init__(self,data):self.data=data;self.pos=0;self.refs=[]
    def take(self,n):
        assert n>=0 and self.pos+n<=len(self.data),(self.pos,n,len(self.data))
        b=self.data[self.pos:self.pos+n];self.pos+=n;return b
    def byte(self):return self.take(1)[0]
    def var(self):
        value=shift=0
        for _ in range(5):
            b=self.byte();value|=(b&127)<<shift
            if b<128:return value
            shift+=7
        raise ValueError('invalid varint')
    def string(self):
        n=self.var();return self.take(n-1).decode('utf-8') if n>1 else ''
    def ref(self,kind):
        start=self.pos;old=self.var();self.refs.append((start,self.pos,kind,old));return old
    def begin(self):self.refs=[];return self.pos
    def end(self,start,**kwargs):return Record(start,self.pos,self.refs.copy(),**kwargs)
    def sequence(self):
        for _ in range(4):self.var()
    def vertices(self,weighted):
        n=self.var()
        if weighted:
            for _ in range(n):
                for _ in range(self.var()):self.ref('bone');self.take(12)
        else:self.take(n*8)
        return n*2
    def curve(self,channels):
        kind=self.byte();assert kind in (0,1,2)
        if kind==2:self.take(channels*16)
    def curve_frames(self,n,channels,byte_values=False):
        size=4+channels*(1 if byte_values else 4);self.take(size)
        for _ in range(n-1):self.take(size);self.curve(channels)
    def slot_timeline(self):
        start=self.pos;kind=self.byte();n=self.var();assert n>0
        if kind==0:
            for _ in range(n):self.take(4);self.var()
        else:
            channels={1:4,2:3,3:7,4:6,5:1}[kind];self.var();self.curve_frames(n,channels,True)
        return self.data[start:self.pos]
    def bone_timeline(self):
        start=self.pos;kind=self.byte();n=self.var();assert n>0
        if kind==10:self.take(n*5)
        else:
            assert kind in range(10);self.var();self.curve_frames(n,2 if kind in (1,4,7) else 1)
        return self.data[start:self.pos]
    def physics_timeline(self):
        start=self.pos;kind=self.byte();n=self.var();assert n>0
        if kind==8:self.take(n*4)
        else:
            assert kind in (0,1,2,4,5,6,7);self.var();self.curve_frames(n,1)
        return self.data[start:self.pos]
    def attachment_timeline(self):
        start=self.pos;self.var();kind=self.byte();n=self.var();assert n>0
        if kind==0:
            self.var();self.take(4)
            for i in range(n):
                count=self.var()
                if count:self.var();self.take(count*4)
                if i<n-1:self.take(4);self.curve(1)
        elif kind==1:self.take(n*12)
        else:raise ValueError('unknown attachment timeline')
        return self.data[start:self.pos]
    def groups(self,fn):
        return [(self.var(),[fn() for _ in range(self.var())]) for _ in range(self.var())]
    def parse(self):
        self.take(8);version=self.string();assert version.startswith('4.2.')
        self.take(20);self.nonessential=self.byte()
        if self.nonessential:self.take(4);self.string();self.string()
        self.strings=[self.string() for _ in range(self.var())];self.prefix=self.data[:self.pos]
        self.bones=[]
        for i in range(self.var()):
            start=self.begin();name=self.string();parent=self.ref('bone') if i else None
            self.take(32);self.var();self.byte()
            if self.nonessential:self.take(4);self.string();self.byte()
            self.bones.append(self.end(start,name=name,parent=parent))
        self.slots=[]
        for _ in range(self.var()):
            start=self.begin();name=self.string();bone=self.ref('bone');self.take(8);self.var();self.var()
            if self.nonessential:self.byte()
            self.slots.append(self.end(start,name=name,bone=bone))
        self.constraints={}
        for kind in ('ik','transform','path','physics'):
            records=[]
            for _ in range(self.var()):
                start=self.begin();name=self.string();order=self.ref('order')
                if kind=='physics':
                    bone=self.ref('bone');driven=(bone,);flags=self.byte()
                    for bit in (2,4,8,16,32,64):
                        if flags&bit:self.take(4)
                    self.take(13)
                    if flags&128:self.take(4)
                    self.take(8);flags=self.byte()
                    if flags&128:self.take(4)
                elif kind in ('ik','transform'):
                    driven=tuple(self.ref('bone') for _ in range(self.var()));target=self.ref('bone');bone=None
                    flags=self.byte()
                    if kind=='ik':
                        if flags&32 and flags&64:self.take(4)
                        if flags&128:self.take(4)
                    else:
                        for bit in (8,16,32,64,128):
                            if flags&bit:self.take(4)
                        flags=self.byte()
                        for bit in (1,2,4,8,16,32,64):
                            if flags&bit:self.take(4)
                else:raise ValueError('Path constraint unsupported for this asset')
                records.append(self.end(start,name=name,bone=bone,driven=driven,order=order))
            self.constraints[kind]=records
        self.skin=[]
        for _ in range(self.var()):
            slot=self.var();atts=[]
            for _ in range(self.var()):
                start=self.begin();name_ref=self.var();flags=self.byte();kind=flags&7
                if flags&8:self.var()
                if kind in (0,2,3):
                    if flags&16:self.var()
                    if flags&32:self.take(4)
                    if flags&64:self.sequence()
                    if kind==0:
                        if flags&128:self.take(4)
                        self.take(24)
                    elif kind==2:
                        hull=self.var();length=self.vertices(bool(flags&128));self.take(length*4)
                        for _ in range((length-hull-2)*3):self.var()
                        if self.nonessential:
                            for _ in range(self.var()):self.var()
                            self.take(8)
                    else:
                        skin_index=self.var();parent_ref=self.var();assert skin_index==0
                        if self.nonessential:self.take(8)
                else:raise ValueError('Unsupported attachment type '+str(kind))
                atts.append(self.end(start,name=self.strings[name_ref-1]))
            self.skin.append((slot,atts))
        assert self.var()==0,'Only default skin supported'
        self.events_start=self.pos;event_count=self.var();assert event_count==0,'Event data unsupported for this asset'
        self.events=self.data[self.events_start:self.pos]
        self.animations=[]
        for _ in range(self.var()):
            start=self.pos;name=self.string();name_bytes=self.data[start:self.pos];old_timeline_count=self.var()
            anim={'name':name,'name_bytes':name_bytes,'old_timeline_count':old_timeline_count}
            anim['slot']=self.groups(self.slot_timeline);anim['bone']=self.groups(self.bone_timeline)
            anim['ik']=[]
            for _ in range(self.var()):
                index=self.var();start=self.pos;n=self.var();self.var();assert n>0
                for frame in range(n):
                    flags=self.byte();self.take(4)
                    if flags&1 and flags&2:self.take(4)
                    if flags&4:self.take(4)
                    if frame and not flags&64 and flags&128:self.take(32)
                anim['ik'].append((index,self.data[start:self.pos]))
            anim['transform']=[]
            for _ in range(self.var()):
                index=self.var();start=self.pos;n=self.var();self.var();self.curve_frames(n,6)
                anim['transform'].append((index,self.data[start:self.pos]))
            assert self.var()==0,'Path timeline unsupported for this asset'
            anim['physics']=self.groups(self.physics_timeline)
            anim['attachment']=[]
            for _ in range(self.var()):
                skin=self.var();assert skin==0
                anim['attachment'].append((skin,self.groups(self.attachment_timeline)))
            start=self.pos;draw_n=self.var();anim['draw_count']=draw_n
            for _ in range(draw_n):
                self.take(4)
                for _ in range(self.var()):self.var();self.var()
            anim['draw']=self.data[start:self.pos]
            start=self.pos;event_n=self.var();assert event_n==0
            anim['event_count']=event_n;anim['events']=self.data[start:self.pos]
            self.animations.append(anim)
        assert self.pos==len(self.data),(self.pos,len(self.data))
        return self

def select(p,hidden):
    slots={i for i,s in enumerate(p.slots) if s.name not in hidden}
    bones={0}|{p.slots[i].bone for i in slots}
    for slot,atts in p.skin:
        if slot in slots:
            for a in atts:bones.update(old for _,_,kind,old in a.refs if kind=='bone')
    selected={kind:set() for kind in p.constraints}
    changed=True
    while changed:
        before=(len(bones),sum(map(len,selected.values())))
        for i in list(bones):
            parent=p.bones[i].parent
            if parent is not None:bones.add(parent)
        for kind,records in p.constraints.items():
            for i,c in enumerate(records):
                if bones.intersection(c.driven):
                    selected[kind].add(i);bones.update(old for _,_,k,old in c.refs if k=='bone')
        changed=before!=(len(bones),sum(map(len,selected.values())))
    maps={'bone':{old:new for new,old in enumerate(sorted(bones))}}
    for kind,indices in selected.items():maps[kind]={old:new for new,old in enumerate(sorted(indices))}
    orders=sorted(p.constraints[k][i].order for k in selected for i in selected[k]);assert len(set(orders))==len(orders)
    maps['order']={old:new for new,old in enumerate(orders)}
    return slots,bones,selected,maps

def write(p,slots,bones,selected,maps):
    out=bytearray(p.prefix);out+=u(len(bones))
    for i in sorted(bones):out+=p.bones[i].write(p,maps)
    out+=u(len(p.slots))
    for i,s in enumerate(p.slots):out+=s.write(p,maps,{('bone',s.bone):0} if i not in slots else None)
    for kind,records in p.constraints.items():
        out+=u(len(selected[kind]))
        for i in sorted(selected[kind]):out+=records[i].write(p,maps)
    skin=[(slot,atts) for slot,atts in p.skin if slot in slots];out+=u(len(skin))
    for slot,atts in skin:
        out+=u(slot)+u(len(atts))
        for a in atts:out+=a.write(p,maps)
    out+=u(0)+p.events+u(len(p.animations));reports=[]
    def group(groups,mapping,allowed):
        keep=[(mapping[i],payloads) for i,payloads in groups if i in allowed]
        return u(len(keep))+b''.join(u(i)+u(len(payloads))+b''.join(payloads) for i,payloads in keep),sum(len(x) for _,x in keep)
    identity={i:i for i in range(len(p.slots))}
    for a in p.animations:
        sections=[];count=0
        for kind,allowed,mapping in [('slot',slots,identity),('bone',bones,maps['bone'])]:
            raw,n=group(a[kind],mapping,allowed);sections.append(raw);count+=n
        for kind in ('ik','transform'):
            keep=[(maps[kind][i],raw) for i,raw in a[kind] if i in selected[kind]]
            sections.append(u(len(keep))+b''.join(u(i)+raw for i,raw in keep));count+=len(keep)
        sections.append(u(0))
        allowed={i+1 for i in selected['physics']}|{0};mapping={i+1:new+1 for i,new in maps['physics'].items()};mapping[0]=0
        raw,n=group(a['physics'],mapping,allowed);sections.append(raw);count+=n
        skins=[]
        for skin,groups in a['attachment']:
            kept=[(i,ps) for i,ps in groups if i in slots]
            if kept:
                raw,n=group(kept,identity,slots);skins.append(u(skin)+raw);count+=n
        sections.append(u(len(skins))+b''.join(skins));count+=bool(a['draw_count'])+bool(a['event_count'])
        out+=a['name_bytes']+u(count)+b''.join(sections)+a['draw']+a['events']
        reports.append({'name':a['name'],'timelines_before':a['old_timeline_count'],'timelines_after':count})
    return bytes(out),reports

def main():
    options=json.loads((SOURCE/'preview-options.json').read_text(encoding='utf-8'))
    p=Parser((SOURCE/'assets/skeleton.skel').read_bytes()).parse()
    slots,bones,selected,maps=select(p,set(options['hidden_slots']))
    raw,animations=write(p,slots,bones,selected,maps)
    # Parse the rewritten draft before asking the production runtime to render it.
    q=Parser(raw).parse();assert len(q.bones)==len(bones) and len(q.constraints['physics'])==len(selected['physics'])
    assets=OUT/'assets';assets.mkdir(parents=True,exist_ok=True);(assets/'skeleton.skel').write_bytes(raw)
    for name in ('skeleton.atlas','texture.png'):shutil.copyfile(SOURCE/'assets'/name,assets/name)
    report={'source':str(SOURCE),'bones_before':len(p.bones),'bones_after':len(bones),
            'physics_before':len(p.constraints['physics']),'physics_after':len(selected['physics']),
            'other_constraints':{k:[len(p.constraints[k]),len(selected[k])] for k in ('ik','transform','path')},
            'removed_bones':[b.name for i,b in enumerate(p.bones) if i not in bones],
            'removed_physics':[c.name for i,c in enumerate(p.constraints['physics']) if i not in selected['physics']],
            'skeleton_bytes_before':len(p.data),'skeleton_bytes_after':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'animations':animations,'retained_slot_count':len(slots),'empty_slot_count':len(p.slots)-len(slots),
            'scale':options['scale'],'bundle_created':False,'firmware_changed':False}
    (OUT/'prune-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    env=os.environ.copy();env['PATH']=str(ROOT/'build/host_mingw/llvm-mingw-20250613-ucrt-x86_64/bin')+os.pathsep+env.get('PATH','')
    layout=ROOT/'build/spine_role_layout/spine_role_layout.exe'
    subprocess.run([str(layout),'scan',str(assets),str(options['scale']),str(OUT/'bounds.json')],check=True,env=env)
    for motion in ('idle','wait1'):
        subprocess.run([str(layout),'preview',str(assets),str(options['scale']),str(ROOT/'build/host_tests/home_render/hero_001_512.rgba'),str(OUT/motion),motion],check=True,env=env)
    from PIL import Image
    for rawfile in OUT.glob('*/*.rgb565'):
        pixels=struct.unpack('<102400H',rawfile.read_bytes());rgb=bytes(c for v in pixels for c in ((v>>11)*255//31,((v>>5)&63)*255//63,(v&31)*255//31))
        Image.frombytes('RGB',(320,320),rgb).save(rawfile.with_suffix('.png'))
    subprocess.run([str(ROOT/'build/spine_role_layout/spine_asset_metrics.exe'),str(assets),str(OUT/'geometry_metrics.json')],check=True,env=env)
    print(json.dumps({k:report[k] for k in ('bones_before','bones_after','physics_before','physics_after','skeleton_bytes_before','skeleton_bytes_after','animations')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
