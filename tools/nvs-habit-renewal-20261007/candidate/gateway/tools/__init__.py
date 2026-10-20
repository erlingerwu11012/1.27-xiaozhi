# 文件路径: tools/__init__.py
"""
工具包：自动扫描 tools 目录下所有 .py 模块并注册到 core.config。
新增工具只需在本目录添加新文件并在文件内调用 config.register(...)，无需修改 main.py。
"""
import os
import pkgutil
import importlib

pkg_path = os.path.dirname(__file__)
for _, name, _ in pkgutil.iter_modules([pkg_path]):
    importlib.import_module(f".{name}", __package__)