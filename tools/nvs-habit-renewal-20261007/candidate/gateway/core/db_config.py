# 文件路径: core/db_config.py
"""
统一数据库配置模块。
支持 .env 中的 DB_HOST、DB_PORT、DB_USER、DB_PASSWORD、DB_NAME。
所有使用数据库的工具应从此模块读取配置，避免重复调用 load_dotenv。
"""
import logging
import os

from dotenv import load_dotenv

# 确保在读取环境变量前已加载 .env（防御性调用，main.py 也会先调用）
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
load_dotenv()

logger = logging.getLogger(__name__)

# 统一使用 DB_* 命名，与 .env 示例保持一致
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "xiaozhi_esp32_server")

# 兼容旧命名 MYSQL_*，若 DB_* 未设置则回退
if not DB_PASSWORD and os.environ.get("MYSQL_PASSWORD"):
    DB_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
if DB_HOST == "127.0.0.1" and os.environ.get("MYSQL_HOST"):
    DB_HOST = os.environ.get("MYSQL_HOST", DB_HOST)
# 同理可扩展 DB_USER、DB_NAME 的 MYSQL_* 回退

if not DB_PASSWORD:
    logger.warning(
        "数据库密码 DB_PASSWORD 为空！请检查 .env 中是否正确配置 DB_PASSWORD，"
        "否则连接可能失败 (using password: NO)。"
    )
