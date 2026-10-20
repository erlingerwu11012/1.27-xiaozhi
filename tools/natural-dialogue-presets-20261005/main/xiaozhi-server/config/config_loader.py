import os
import yaml
from collections.abc import Mapping
from config.manage_api_client import init_service, get_server_config, get_agent_models


def get_project_dir():
    """获取项目根目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"


def read_config(config_path):
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config


def load_config():
    """加载配置文件"""
    from core.utils.cache.manager import cache_manager, CacheType

    # 检查缓存
    cached_config = cache_manager.get(CacheType.CONFIG, "main_config")
    if cached_config is not None:
        return cached_config

    default_config_path = get_project_dir() + "config.yaml"
    custom_config_path = get_project_dir() + "data/.config.yaml"

    # 加载默认配置
    default_config = read_config(default_config_path)
    custom_config = read_config(custom_config_path)

    if custom_config.get("manager-api", {}).get("url"):
        # 先合并本地全量配置（保留 config.yaml 中的 face 等新增配置节），再交由 API 覆盖
        merged_local = merge_configs(default_config, custom_config)
        config = get_config_from_api(merged_local)
    else:
        # 合并配置
        config = merge_configs(default_config, custom_config)
    # 初始化目录
    ensure_directories(config)

    # 缓存配置
    cache_manager.set(CacheType.CONFIG, "main_config", config)
    return config


def get_config_from_api(config):
    """从Java API获取配置"""
    # 初始化API客户端
    init_service(config)

    # 获取服务器配置
    config_data = get_server_config()
    if config_data is None:
        raise Exception("Failed to fetch server config from API")

    config_data["read_config_from_api"] = True
    config_data["manager-api"] = {
        "url": config["manager-api"].get("url", ""),
        "secret": config["manager-api"].get("secret", ""),
    }
    # server：本地 ip/port/http_port/vision_explain/auth_key 优先，MQTT 相关从 API 下发
    api_server = config_data.get("server") or {}
    local_server = config.get("server") or {}
    merged_server = dict(api_server)
    if local_server:
        for k in (
            "ip",
            "port",
            "http_port",
            "vision_explain",
            "vision_identity",
            "auth_key",
            "auth",
            "face",
            "public_base_url",
            "reminder_control_url",
            "websocket",
            "face_enrollment_session_url",
            "face_enrollment_timeout_seconds",
        ):
            if local_server.get(k) is not None:
                merged_server[k] = local_server[k]
        # 正面单模板：仅这个字段本地优先。用 `in` 保留显式 false；
        # 不整份覆盖 server。字段缺失时留给运行时环境变量回退。
        for k in (
            "face_enrollment_front_only_enabled",
        ):
            if k in local_server:
                merged_server[k] = local_server[k]
        # 用户本人左右方向指导（user_relative_v1）：与 front_only 同样本地优先；
        # 显式 false / [] 必须保留，不能被 manager-api 或环境变量重新打开。
        for k in (
            "face_enrollment_user_relative_enabled",
            "face_enrollment_user_relative_allowlist",
        ):
            if k in local_server:
                merged_server[k] = local_server[k]
    config_data["server"] = merged_server
    # 测试日志开关仅来自本地 yaml，避免被智控台配置覆盖丢失
    if config.get("trace_log"):
        config_data["trace_log"] = merge_configs(
            config_data.get("trace_log") or {}, config.get("trace_log") or {}
        )
    # 时钟兼容仅来自本地 yaml，不走智控台；开启后对所有设备生效，
    # 实际 compat 行为由真实时间戳自适应判定。
    # 禁止把本地 VAD.min_silence_duration_ms 盖到 API 上（现网句尾阈值以智控台为准）。
    apply_local_only_top_level(config, config_data)
    return config_data


LOCAL_ONLY_TOP_LEVEL_KEYS = (
    "operation_control",
    "conversation_validation",
    "audio_clock_compat_enabled",
    "prompt_pipeline",
    "speech_expression",
    "llm_observability",
    "context_compress",
)


def apply_local_only_top_level(local_config, api_config):
    """Copy local-only gray flags onto API-merged config without touching VAD/LLM/TTS."""
    if not isinstance(local_config, Mapping) or not isinstance(api_config, Mapping):
        return api_config
    for key in LOCAL_ONLY_TOP_LEVEL_KEYS:
        if key in local_config:
            api_config[key] = local_config[key]
    return api_config


def get_private_config_from_api(config, device_id, client_id):
    """从Java API获取私有配置"""
    return get_agent_models(device_id, client_id, config["selected_module"])


def ensure_directories(config):
    """确保所有配置路径存在"""
    dirs_to_create = set()
    project_dir = get_project_dir()  # 获取项目根目录
    # 日志文件目录
    log_dir = config.get("log", {}).get("log_dir", "tmp")
    dirs_to_create.add(os.path.join(project_dir, log_dir))
    trace_dir = (config.get("trace_log") or {}).get("dir") or "logs/trace"
    if not os.path.isabs(trace_dir):
        dirs_to_create.add(os.path.join(project_dir, trace_dir))
    else:
        dirs_to_create.add(trace_dir)

    # ASR/TTS模块输出目录
    for module in ["ASR", "TTS"]:
        if config.get(module) is None:
            continue
        for provider in config.get(module, {}).values():
            output_dir = provider.get("output_dir", "")
            if output_dir:
                dirs_to_create.add(output_dir)

    # 根据selected_module创建模型目录
    selected_modules = config.get("selected_module", {})
    for module_type in ["ASR", "LLM", "TTS"]:
        selected_provider = selected_modules.get(module_type)
        if not selected_provider:
            continue
        if config.get(module) is None:
            continue
        if config.get(selected_provider) is None:
            continue
        provider_config = config.get(module_type, {}).get(selected_provider, {})
        output_dir = provider_config.get("output_dir")
        if output_dir:
            full_model_dir = os.path.join(project_dir, output_dir)
            dirs_to_create.add(full_model_dir)

    # 统一创建目录（保留原data目录创建）
    for dir_path in dirs_to_create:
        try:
            os.makedirs(dir_path, exist_ok=True)
        except PermissionError:
            print(f"警告：无法创建目录 {dir_path}，请检查写入权限")


def merge_configs(default_config, custom_config):
    """
    递归合并配置，custom_config优先级更高

    Args:
        default_config: 默认配置
        custom_config: 用户自定义配置

    Returns:
        合并后的配置
    """
    if not isinstance(default_config, Mapping) or not isinstance(
        custom_config, Mapping
    ):
        return custom_config

    merged = dict(default_config)

    for key, value in custom_config.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value

    return merged
