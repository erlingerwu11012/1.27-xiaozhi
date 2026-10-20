import os
import sys
import importlib
from config.logger import setup_logging

logger = setup_logging()


def create_instance(class_name, *args, **kwargs):
    here = os.path.dirname(os.path.abspath(__file__))
    core_dir = os.path.dirname(here)
    module_file = os.path.join(
        core_dir, "providers", "memory", class_name, f"{class_name}.py"
    )
    if os.path.isfile(module_file):
        lib_name = f"core.providers.memory.{class_name}.{class_name}"
        if lib_name not in sys.modules:
            sys.modules[lib_name] = importlib.import_module(f"{lib_name}")
        return sys.modules[lib_name].MemoryProvider(*args, **kwargs)

    raise ValueError(f"不支持的记忆服务类型: {class_name}")
