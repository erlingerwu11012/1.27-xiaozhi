"""Read-only live UART and production log capture, requested by the user."""
import argparse
import importlib.util
from pathlib import Path

stage = Path(__file__).resolve().parent
source = stage.parent / 'experience-repair-20261009/capture_device_test.py'
spec = importlib.util.spec_from_file_location('live_capture_base', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.FILES = [
    '/root/.pm2/logs/xiaozhi-server-out.log',
    '/root/.pm2/logs/xiaozhi-server-error.log',
    '/root/.pm2/logs/manager-api-out.log',
    '/root/.pm2/logs/manager-api-error.log',
]
# Start at current EOF; old log failures must not enter this test window.
module.READER = module.READER.replace(
    'else max(0,st.st_size-262144)', 'else st.st_size')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', default='COM9')
    parser.add_argument('--server', default='root@121.40.239.140')
    parser.add_argument('--seconds', type=int, default=0)
    module.capture(parser.parse_args())
