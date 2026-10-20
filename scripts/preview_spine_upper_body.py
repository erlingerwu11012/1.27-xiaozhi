"""Prepare an upper-body asset draft and render it; never create an OTA bundle."""
from pathlib import Path
import json, struct, shutil, subprocess, os
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'releases/hero_001_compact_20261002/assets'
OUT=ROOT/'build/spine_role_layout/hero_001_upper_preview_20261002'

class Reader:
    def __init__(self, data): self.data=data; self.pos=8
    def byte(self): v=self.data[self.pos];self.pos+=1;return v
    def varint(self):
        v=shift=0
        for _ in range(5):
            b=self.byte();v|=(b&127)<<shift
            if b<128:return v
            shift+=7
        raise ValueError('invalid varint')
    def string(self):
        n=self.varint()
        if n<=1:return ''
        s=self.data[self.pos:self.pos+n-1].decode('utf-8');self.pos+=n-1;return s
    def skip(self,n):self.pos+=n

def main():
    OUT.mkdir(parents=True,exist_ok=True);assets=OUT/'assets';assets.mkdir(exist_ok=True)
    raw=bytearray((SOURCE/'skeleton.skel').read_bytes());r=Reader(raw)
    version=r.string();assert version.startswith('4.2.')
    r.skip(20);nonessential=r.byte()
    if nonessential:r.skip(4);r.string();r.string()
    for _ in range(r.varint()):r.string()
    root_x=root_y=None
    for i in range(r.varint()):
        r.string()
        if i:r.varint()
        else:root_x=r.pos+4;root_y=r.pos+8
        r.skip(32);r.varint();r.byte()
        if nonessential:r.skip(4);r.string();r.byte()
    hidden=[];visible=[];removed_attachment_refs=[]
    for _ in range(r.varint()):
        name=r.string();r.varint();alpha=r.pos+3;r.skip(8)
        ref_start=r.pos;r.varint();ref_end=r.pos;r.varint()
        if nonessential:r.byte()
        hide=(name.startswith(('wuqi_','shitou_','huo','gouyu_','tui_')) or
              name in ('Red_Di','daizi_02','daizi_03_1','daizi_04','daizi_05'))
        if hide:
            raw[alpha]=0;hidden.append(name);removed_attachment_refs.append((ref_start,ref_end))
        else:visible.append(name)
    assert len(hidden)>40 and 'wuqi_3' in hidden and 'tou' in visible
    scale=0.135
    # Preserve the upper costume and both hands; the lowest coat edge ends near y=290.
    struct.pack_into('>f',raw,root_x,-136.5)
    struct.pack_into('>f',raw,root_y,30/scale-1220)
    # Detach instead of merely making slots transparent: animated color keys
    # must not bring flame/sword/leg attachments back on subsequent frames.
    for start,end in reversed(removed_attachment_refs):raw[start:end]=b'\x00'
    (assets/'skeleton.skel').write_bytes(raw)
    for n in ('skeleton.atlas','texture.png'):shutil.copyfile(SOURCE/n,assets/n)
    (OUT/'preview-options.json').write_text(json.dumps(dict(scale=scale,hidden_slots=hidden,
        visible_slots=visible,method='detach slot setup attachments; no bone/physics pruning yet',
        target=[320,320],root=[-136.5,30/scale-1220],bundle_created=False),ensure_ascii=False,indent=2),encoding='utf-8')
    exe=ROOT/'build/spine_role_layout/spine_role_layout.exe'
    env=os.environ.copy();env['PATH']=str(ROOT/'build/host_mingw/llvm-mingw-20250613-ucrt-x86_64/bin')+os.pathsep+env.get('PATH','')
    subprocess.run([str(exe),'scan',str(assets),str(scale),str(OUT/'bounds.json')],check=True,env=env)
    scan=json.loads((OUT/'bounds.json').read_text(encoding='utf-8'))
    assert not set(hidden)&set(scan['attachments']), 'Hidden slots became visible during animation'
    for motion in ('idle','wait1'):
        subprocess.run([str(exe),'preview',str(assets),str(scale),str(ROOT/'build/host_tests/home_render/hero_001_512.rgba'),str(OUT/motion),motion],check=True,env=env)
    # Decode native RGB565 renderer output into PNG without editing any source artwork.
    from PIL import Image
    for rawfile in OUT.glob('*/*.rgb565'):
        pixels=struct.unpack('<102400H',rawfile.read_bytes())
        rgb=bytes(c for v in pixels for c in ((v>>11)*255//31,((v>>5)&63)*255//63,(v&31)*255//31))
        Image.frombytes('RGB',(320,320),rgb).save(rawfile.with_suffix('.png'))
    print(json.dumps(dict(preview=str(OUT/'idle/idle_0.png'),hidden_slots=len(hidden),bounds=scan['bounds']),indent=2))

if __name__=='__main__':main()
