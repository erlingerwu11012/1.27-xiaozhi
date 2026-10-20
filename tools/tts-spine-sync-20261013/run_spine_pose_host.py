from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from run_ws_audio_send_host_test import function

def main():
    stage=Path(__file__).parent
    source=(stage/'spine_pose_host.cpp').read_text(encoding='utf-8')
    bridge='\n'.join(function('components/cubicat_home_spine/cubicat-port/spine_node.cpp',s).replace('SpineNode::','Bridge::')
        for s in ('TrackEntry* SpineNode::setAnimation(int trackIndex, const std::string &name', 'void SpineNode::clearTrack('))
    bridge=bridge.replace('TrackEntry*','spine::TrackEntry*').replace('Animation *','spine::Animation *')
    player='\n'.join(function('main/display/cubicat_home_player.cc',s).replace('void Apply','void Player::Apply')
        for s in ('void ApplyState(', 'void ApplyTtsPlayback('))
    out=ROOT/'build/tts_spine_sync';out.mkdir(parents=True,exist_ok=True)
    generated=out/'spine_pose.cpp';generated.write_text(source.replace('// @BRIDGE',bridge).replace('// @PLAYER',player),encoding='utf-8')
    runtime=ROOT/'components/cubicat_home_spine/spine-cpp_4.2'
    flags=['-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(runtime/'include'),'-I'+str(runtime.parent/'cubicat-port')]
    objdir=out/'spine_objects';objdir.mkdir(exist_ok=True)
    def compile_one(path):
        obj=objdir/(path.stem+'.o')
        if not obj.exists() or obj.stat().st_mtime<path.stat().st_mtime:
            subprocess.run(['g++',*flags,'-c',str(path),'-o',str(obj)],check=True)
        return str(obj)
    with ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile_one,sorted((runtime/'src/spine').glob('*.cpp'))))
    binary=out/'spine_pose'
    subprocess.run(['g++',*flags,str(generated),*objects,'-o',str(binary)],check=True)
    subprocess.run([str(binary),str(ROOT/'main/assets/cubicat_spine_default_42')],check=True,timeout=30)

if __name__=='__main__':main()
