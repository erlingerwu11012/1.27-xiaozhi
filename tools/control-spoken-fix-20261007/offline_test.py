"""Run one suite with no production config, manager network or real device."""
import runpy, sys, os
from pathlib import Path
from unittest.mock import MagicMock
root = Path(os.environ.get('TEST_ROOT') or (Path(__file__).parent / 'candidate/main/xiaozhi-server'))
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'test'))
import config.config_loader
def offline(config):
    result = dict(config)
    result['read_config_from_api'] = False
    result['manager-api'] = {}
    return result
config.config_loader.get_config_from_api = offline
import config.settings
config.settings.config_file_valid = True
import config.logger
config.logger.setup_logging = lambda: MagicMock()
path = str(root / 'test' / ('test_' + sys.argv[1] + '.py'))
sys.argv = [path]
namespace = runpy.run_path(path, run_name='__main__')
if Path(path).name == 'test_operation_pipeline.py':
    import unittest
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace['OperationPipelineTests'])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
