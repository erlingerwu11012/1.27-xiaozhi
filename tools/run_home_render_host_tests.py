#!/usr/bin/env python3
"""Compile production renderer and snapshot queue with host-only RTOS stubs.
Returns 2 (unverified) when no native compiler is available. Does not flash.
Optional --role DIR converts a local PNG and compares actual Spine 4.2 poses.
"""
from pathlib import Path
import argparse, json, os, re, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1]
ENGINE=ROOT/'components/cubicat_home_engine'
SPINE=ROOT/'components/cubicat_home_spine/spine-cpp_4.2'
STUBS=ROOT/'tools/host_stubs/home_render'
def main():
    p=argparse.ArgumentParser();p.add_argument('--compiler');p.add_argument('--role',action='append',default=[]);p.add_argument('--sanitize',action='store_true');a=p.parse_args()
    compiler=a.compiler or shutil.which('clang++') or shutil.which('g++')
    if not compiler:
        candidates=list((ROOT/'build/host_mingw').glob('**/bin/g++.exe'))
        compiler=str(candidates[0]) if candidates else None
    if not compiler:print('NOT VERIFIED: no host C++ compiler');return 2
    out=ROOT/('build/host_tests/home_render_asan' if a.sanitize else 'build/host_tests/home_render');out.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env['PATH']=str(Path(compiler).parent)+os.pathsep+env.get('PATH','')
    if a.sanitize:env['ASAN_OPTIONS']='detect_leaks=0'
    flags=['-std=c++17','-O2','-pthread','-DCONFIG_ENABLE_BILINEAR_FILTER=1','-DCONFIG_ESP_DEFAULT_CPU_FREQ_MHZ=240','-ffp-contract=off','-Wno-unused-variable','-Wno-ignored-qualifiers','-Wno-reorder',f'-I{STUBS}',f'-I{ENGINE}',f'-I{ROOT}/main/display',f'-I{SPINE}/include',f'-I{ROOT}/components/cubicat_home_spine/cubicat-port']
    if a.sanitize:flags+=['-fsanitize=address','-fno-omit-frame-pointer']
    # Compile the saved Git baseline separately; reference files stay ignored.
    def saved(path):
        return subprocess.check_output(['git','show','75fbc1ba:'+path],cwd=ROOT).decode('utf-8')
    original_header=saved('components/cubicat_home_engine/graphic_engine/renderer/renderer.h')
    start=original_header.index('class Renderer\n');end=original_header.rfind('\n}\n')
    reference_header=out/'renderer_reference.h'
    reference_header.write_text('#pragma once\n#include "graphic_engine/renderer/renderer.h"\nnamespace cubicat {\n'+re.sub(r'\bRenderer\b','ReferenceRenderer',original_header[start:end])+'\n}\n',encoding='utf-8')
    original=saved('components/cubicat_home_engine/graphic_engine/renderer/renderer.cpp')
    original=original.replace('#include "renderer.h"','#include "renderer_reference.h"').replace('"../','"graphic_engine/')
    original=re.sub(r'\bRenderer\b','ReferenceRenderer',original).replace('RegionClip(','ReferenceRegionClip(')
    reference_source=out/'renderer_reference.cpp';reference_source.write_text(original,encoding='utf-8')
    # Also compile the exact first-round renderer, with separate private types.
    prev_header=subprocess.check_output(['git','show','26cfcc19:components/cubicat_home_engine/graphic_engine/renderer/renderer.h'],cwd=ROOT).decode('utf-8')
    prev_source=subprocess.check_output(['git','show','26cfcc19:components/cubicat_home_engine/graphic_engine/renderer/renderer.cpp'],cwd=ROOT).decode('utf-8')
    def rename_prev(s):
        for name in ('Renderer','RendererState','DrawPacket','RasterContext','EdgeStart','RasterAllocator'):
            s=re.sub(r'\b'+name+r'\b','Previous'+name,s)
        return s.replace('RegionClip(', 'PreviousRegionClip(')
    section=prev_header[prev_header.index('struct RasterContext;'):prev_header.rfind('\n}\n')]
    (out/'renderer_previous.h').write_text('#pragma once\n#include "graphic_engine/renderer/renderer.h"\nnamespace cubicat {\n'+rename_prev(section)+'\n}\n',encoding='utf-8')
    prev_source=prev_source.replace('#include "renderer.h"','#include "renderer_previous.h"').replace('"../','"graphic_engine/').replace('#include "raster_texture.h"','#include "graphic_engine/renderer/raster_texture.h"')
    previous_source=out/'renderer_previous.cpp';previous_source.write_text(rename_prev(prev_source),encoding='utf-8')
    flags.append(f'-I{out}')
    source=[reference_source,previous_source,STUBS/'host_runtime.cpp',ENGINE/'core/memory_object.cpp',ENGINE/'core/id_object.cpp',ENGINE/'graphic_engine/drawable/texture.cpp',ENGINE/'graphic_engine/drawable/material.cpp',ENGINE/'graphic_engine/drawable/drawable.cpp',ENGINE/'graphic_engine/drawable/polygon2d.cpp',ENGINE/'graphic_engine/math/common.cpp',ENGINE/'graphic_engine/renderer/renderer.cpp',ENGINE/'utils/home_render_options.cpp',ROOT/'main/display/home_frame_pipeline.cc',ROOT/'main/display/standby_clock.cc',ROOT/'tools/test_home_render_host.cpp']
    source += [ENGINE/'graphic_engine/node.cpp', ENGINE/'graphic_engine/node2d.cpp',
               ENGINE/'core/message/message_tube.cpp',
               ROOT/'components/cubicat_home_spine/cubicat-port/spine_node.cpp',
               ROOT/'components/cubicat_home_spine/cubicat-port/texture_loader.cpp']
    source+=sorted((SPINE/'src/spine').glob('*.cpp'))
    newest_header=max(h.stat().st_mtime for base in (STUBS,ENGINE,SPINE/"include",ROOT/"main/display") for h in base.rglob("*.h"))
    def compile_one(s):
        obj=out/(s.parent.name+'_'+s.name+'.o')
        if not obj.exists() or obj.stat().st_mtime<s.stat().st_mtime or obj.stat().st_mtime<newest_header:
            result=subprocess.run([compiler,*flags,'-c',str(s),'-o',str(obj)],capture_output=True,text=True,encoding='utf-8',errors='replace',env=env)
            if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        return str(obj)
    with ThreadPoolExecutor(max_workers=6) as pool:objects=list(pool.map(compile_one,source))
    exe=out/'test_home_render.exe'
    cmd=[compiler,*flags,*objects,'-o',str(exe)]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',env=env)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    cmd=[str(exe),str(out)]
    from PIL import Image
    import struct
    for directory in a.role:
        original=Path(directory)
        role=out/'roles'/original.name;role.mkdir(parents=True,exist_ok=True)
        for canonical, pattern in [('texture.png','*.png'),('skeleton.atlas','*.atlas'),('skeleton.skel','*.skel')]:
            source=original/canonical
            if not source.exists():
                matches=list(original.glob(pattern))
                if len(matches)!=1:raise RuntimeError(f'Ambiguous {pattern} in {original}')
                source=matches[0]
            shutil.copyfile(source,role/canonical)
        im=Image.open(role/'texture.png').convert('RGBA')
        raw=out/(role.name+'.rgba')
        data=im.tobytes();converted=bytearray(len(data))
        converted[0::4]=data[3::4];converted[1::4]=data[2::4]
        converted[2::4]=data[1::4];converted[3::4]=data[0::4]
        raw.write_bytes(converted)
        cmd +=[str(role),str(raw)]
    r=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,timeout=180)
    (out/'test_results.txt').write_text(r.stdout+r.stderr,encoding='utf-8');print(r.stdout+r.stderr)
    if r.returncode:return 1
    # Convert actual RGB565 captures to viewable images for manual inspection.
    for raw in out.glob('frame_*.rgb565'):
        values=struct.unpack('<102400H',raw.read_bytes());rgb=bytes(channel for v in values for channel in (((v>>11)*255//31),((v>>5&63)*255//63),((v&31)*255//31)))
        Image.frombytes('RGB',(320,320),rgb).save(raw.with_suffix('.png'))
    print('ALL HOME RENDER HOST TESTS PASSED');return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print(e,file=sys.stderr);sys.exit(1)
