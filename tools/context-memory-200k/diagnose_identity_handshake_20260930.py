"""Read-only production probe. Prints protocol metadata, never message bodies."""
from collections import Counter
from pathlib import Path
import json
import re
import subprocess

pm = json.loads(subprocess.run(["pm2", "jlist"], check=True, capture_output=True, text=True).stdout)
for name in ("xiaozhi-server", "manager-api"):
    process = next((entry for entry in pm if entry["name"] == name), None)
    if not process:
        print(json.dumps({"service": name, "exists": False}))
        continue
    print(json.dumps({"service": name, "pm2_status": process["pm2_env"].get("status")}))
    for stream in ("pm_out_log_path", "pm_err_log_path"):
        path = Path(process["pm2_env"].get(stream) or "")
        if not path.exists():
            continue
        lines = path.read_bytes()[-32_000_000:].decode("utf-8", "replace").splitlines()
        if name == "xiaozhi-server":
            # Include the preceding connection/handshake window.
            window = [line for line in lines if re.search(r"260930 (01:5[8-9]|02:0[0-5]):", line)]
            labels = {
                "mcp_initialize": r"MCP initialize|MCP初始化|发送MCP初始化|method.?initialize",
                "mcp_catalog": r"MCP catalog|tools/list",
                "mcp_unpack": r"MCP解包",
                "mcp_stale": r"MCP stale_result",
                "identity_sync": r"identity/sync|identity_synced_version|目录同步",
                "identity_unknown": r"identity_unknown|没识别到你的身份",
                "archive_reject": r"存档归属无效",
                "memory_tool": r"执行工具: memory_search",
                "device_hello": r"helloHandler|收到设备.*hello",
                "device_config_error": r"获取设备配置失败|device_config_fallback",
                "voiceprint_enabled": r"声纹识别已启用|声纹识别功能已在连接时动态启用",
                "voiceprint_missing_url": r"声纹识别URL未配置",
                "directory_ready": r"directory_sync_ready",
                "directory_rejected": r"directory_sync_rejected",
                "directory_failed": r"directory_sync_failed",
            }
            counts = {label: sum(bool(re.search(pattern, line, re.I)) for line in window)
                      for label, pattern in labels.items()}
            print(json.dumps({"service": name, "stream": stream,
                              "window_lines": len(window), "counts": counts}, ensure_ascii=False))
            for line in window:
                if not any(re.search(labels[label], line, re.I) for label in
                           ("mcp_initialize", "mcp_catalog", "mcp_unpack", "mcp_stale",
                            "identity_sync", "device_config_error", "voiceprint_enabled",
                            "voiceprint_missing_url", "directory_ready", "directory_rejected",
                            "directory_failed")):
                    continue
                at = re.search(r"260930 (\d\d:\d\d:\d\d)", line)
                tag = re.search(r"\[([^\]]*MCP[^\]]*|core\.[^\]]+)\]", line)
                marks = [label for label, pattern in labels.items() if re.search(pattern, line, re.I)]
                print(json.dumps({"service": name, "at": at.group(1) if at else None,
                                  "tag": tag.group(1) if tag else None, "markers": marks,
                                  "sync_reason": re.search(r"directory_sync_rejected reason=([a-z_]+)", line).group(1)
                                      if re.search(r"directory_sync_rejected reason=([a-z_]+)", line) else None,
                                  "version_match": re.search(r"version_match=(True|False)", line).group(1)
                                      if re.search(r"version_match=(True|False)", line) else None},
                                 ensure_ascii=False))
        else:
            window = [line for line in lines if "2026-09-30" in line and
                      re.search(r"(01:5[8-9]|02:0[0-5]):", line)]
            patterns = {
                "capability_endpoint": r"internal/capability",
                "capability_failure": r"能力声明无效|reportCapability|identity.capability",
                "state_endpoint": r"internal/state/",
                "archive_reject": r"存档归属无效",
                "http_error": r"\b(4\d\d|5\d\d)\b",
            }
            counts = {label: sum(bool(re.search(pattern, line, re.I)) for line in window)
                      for label, pattern in patterns.items()}
            print(json.dumps({"service": name, "stream": stream,
                              "window_lines": len(window), "counts": counts}, ensure_ascii=False))

mysql = ["docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
query = """SELECT JSON_OBJECT('has_capability', c.device_id IS NOT NULL,
       'identity', c.identity_version, 'cleanup', c.cleanup_version,
       'firmware', c.firmware_version)
FROM xiaozhi_esp32_server.ai_device d
LEFT JOIN xiaozhi_esp32_server.ai_device_identity_capability c
  ON c.device_id=d.mac_address AND c.account_id=d.user_id
WHERE d.mac_address='ac:a7:04:fd:20:2c';"""
rows = subprocess.run(mysql, input=query, text=True, capture_output=True, check=True).stdout.splitlines()
print(json.dumps({"capability": [json.loads(row) for row in rows if row]}, ensure_ascii=False))
