# 文件路径: main.py
import os
import uvicorn
from dotenv import load_dotenv

# 最先加载 .env，确保数据库等配置在 import tools 之前可用
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path=_env_path)
load_dotenv()  # 同时加载当前工作目录的 .env

import tools  # 自动扫描 tools/ 下所有模块并注册工具，新增 .py 无需改本文件
from core.config import config

# 根据 env 构建“已配置项”列表，/list-tools 会隐藏这些参数，调用时自动补全
config.build_internal_config()

from core.server import app, _build_list_tools_payload


# ---------- 工具发现接口：必须在本文件注册，保证先加载 tools 再暴露，返回真实工具列表 ----------
# title 由各工具文件内 @tool_meta(title="中文名") 动态提供，无需在此维护字典
@app.get("/list_tools")
async def list_tools():
    """返回当前网关已注册工具的 JSON 数组，每项含 name, title, description, input_schema。供 Java 管理台同步插件列表。"""
    return _build_list_tools_payload()


@app.get("/list-tools")
async def list_tools_hyphen():
    """与 /list_tools 同义，兼容不同命名。"""
    return _build_list_tools_payload()


if __name__ == "__main__":
    print("🚀 小智统一 MCP 网关正在启动...")
    # 必须用 python main.py 或 uvicorn main:app 启动，否则工具列表为空
    uvicorn.run(app, host="127.0.0.1", port=8123, log_level="info")