from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from run_ws_audio_send_host_test import function

def main():
    source=(Path(__file__).parent/'audio_output_host.cpp').read_text(encoding='utf-8')
    methods=[function('main/audio/audio_service.cc',sig) for sig in (
        'void AudioService::AudioOutputTask(', 'bool AudioService::IsPlaybackDrained(',
        'TtsPlaybackSnapshot AudioService::GetTtsPlaybackSnapshot(', 'void AudioService::ResetDecoder(')]
    out=ROOT/'build/tts_spine_sync';out.mkdir(parents=True,exist_ok=True)
    generated=out/'audio_output.cpp';generated.write_text(source.replace('// @METHODS','\n'.join(methods)),encoding='utf-8')
    binary=out/'audio_output'
    subprocess.run(['g++','-std=c++17','-O1','-g','-pthread','-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all','-I'+str(ROOT/'main'),str(generated),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=30)

if __name__=='__main__':main()
