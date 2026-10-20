from pathlib import Path
import tarfile
R=Path(__file__).resolve().parents[2];S=Path(__file__).parent
with tarfile.open(S/'firmware-host.tgz','w:gz') as t:
    for name in ['main/vision_credentials.h','main/vision_credentials.cc','main/http.h','main/camera_image_buffer.h','tools/test_vision_credentials_host.cpp','tools/run_vision_credentials_host_test.py']:
        t.add(R/name,arcname=name)
