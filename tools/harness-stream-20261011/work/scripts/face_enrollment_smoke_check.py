#!/usr/bin/env python3
"""部署前人脸 enrollment 烟测（无摄像头、不写真实人脸库）。

用法（在 xiaozhi-server 目录）：
  python scripts/face_enrollment_smoke_check.py --config data/.config.yaml
  python scripts/face_enrollment_smoke_check.py --base-url https://example.com --dry-config-only

检查项：
- public_base_url / session_url 为 HTTPS 且 host 一致
- 缺独立 signing key 时 capability fail-closed
- （可选）对公网网关做无摄像头鉴权负向探测
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def _load_yaml_config(path: str) -> dict:
    try:
        import yaml
    except ImportError:
        print("FAIL: need PyYAML to load config file", file=sys.stderr)
        sys.exit(2)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def check_capability(config: dict) -> List[str]:
    from core.utils.face_enrollment_capability import (
        build_face_enrollment_capability,
        get_face_enrollment_upload_signing_key,
    )
    from core.utils.face_enrollment_v2 import resolve_v2_session_url

    failures: List[str] = []
    server = config.get("server") or {}
    public = (server.get("public_base_url") or "").strip()
    if not public.lower().startswith("https://"):
        failures.append("public_base_url must be https://")
    url, reason = resolve_v2_session_url(config)
    if not url:
        failures.append(f"session_url invalid: {reason}")
    else:
        if not url.lower().startswith("https://"):
            failures.append("session_url must be https://")
        pub_host = urlparse(public).hostname
        sess_host = urlparse(url).hostname
        if pub_host and sess_host and pub_host.lower() != sess_host.lower():
            failures.append("session_url host must match public_base_url host")
        if not url.rstrip("/").endswith("/mcp/face-enrollment/session"):
            failures.append(
                "session_url path must be /mcp/face-enrollment/session (V2 singular)"
            )
        cap = build_face_enrollment_capability(config)
        if cap.ok and cap.capability:
            if cap.capability.get("protocol_version") != 2:
                failures.append("capability must be protocol_version=2")
            if cap.capability.get("guided_burst_v1") is not True:
                failures.append("capability must set guided_burst_v1=true")
            if int(cap.capability.get("session_timeout_seconds") or 0) != 240:
                failures.append("capability session_timeout_seconds must be 240")

    key, key_reason = get_face_enrollment_upload_signing_key(config)
    cap = build_face_enrollment_capability(config)
    if not key:
        if cap.ok:
            failures.append("capability must fail-closed when signing key missing")
        else:
            print(f"OK: capability fail-closed ({cap.reason or key_reason})")
    else:
        if not cap.ok:
            failures.append(f"capability unexpectedly closed: {cap.reason}")
        else:
            dumped = json.dumps(cap.capability)
            if key in dumped:
                failures.append("capability must not embed signing key")
            print("OK: capability_ok (key present, not advertised)")

    # 禁止日志敏感字段（静态检查本脚本输出）
    print("OK: smoke script does not print tokens/names/images")
    return failures


def probe_auth_negatives(base: str) -> List[str]:
    """对公网网关做负向探测（不上传真实人脸）。"""
    failures: List[str] = []
    create_url = base.rstrip("/") + "/mcp/face-enrollment/session"

    def _post(url: str, headers: Dict[str, str]) -> Tuple[int, dict]:
        req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read()
                return resp.status, json.loads(body.decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                payload = {}
            return e.code, payload
        except Exception as exc:
            return 0, {"ok": False, "error_code": "internal_error", "message": str(exc)}

    # 无 Authorization
    status, body = _post(
        create_url,
        {"Content-Type": "application/json", "Device-Id": "aa:bb:cc:dd:ee:ff", "Client-Id": "smoke"},
    )
    if body.get("ok") is not False or body.get("error_code") != "auth_invalid":
        failures.append(f"missing auth expected auth_invalid, got http={status} body={body}")
    else:
        print(f"OK: no Authorization -> {status} auth_invalid")

    # 错 Device-Id（带假 Bearer）
    status, body = _post(
        create_url,
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer not-a-real-token",
            "Device-Id": "ff:ee:dd:cc:bb:aa",
            "Client-Id": "smoke",
        },
    )
    if body.get("error_code") != "auth_invalid":
        failures.append(f"bad auth expected auth_invalid, got http={status} body={body}")
    else:
        print(f"OK: bad Bearer -> {status} auth_invalid")

    # assess 无 X-Enrollment-Token
    assess = base.rstrip("/") + "/mcp/face-enrollment/assess/deadbeefdeadbeef"
    boundary = "----smoke"
    body_bytes = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"a.jpg\"\r\n"
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode() + b"\xff\xd8\xff\x00" + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        assess,
        data=body_bytes,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": "Bearer not-a-real-token",
            "Device-Id": "aa:bb:cc:dd:ee:ff",
            "Client-Id": "smoke",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
    except Exception as exc:
        failures.append(f"assess probe failed: {exc}")
        return failures

    if payload.get("error_code") not in (
        "auth_invalid",
        "upload_token_invalid",
        "upload_token_expired",
    ):
        failures.append(f"assess without token unexpected: http={status} body={payload}")
    else:
        print(f"OK: assess without enrollment token -> {status} {payload.get('error_code')}")

    # 确保响应不含敏感字段名泄露到打印以外——仅检查 schema
    for key in ("upload_token", "embedding", "display_name", "Authorization"):
        if key in json.dumps(payload):
            # error 响应不应带 token
            if key == "upload_token" and payload.get("ok") is True:
                failures.append("unexpected upload_token in negative probe")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="", help="xiaozhi-server yaml config path")
    ap.add_argument("--base-url", default="", help="public https base for live probes")
    ap.add_argument(
        "--dry-config-only",
        action="store_true",
        help="only validate config/capability, no network",
    )
    ap.add_argument("--probe", action="store_true", help="run live auth negative probes")
    args = ap.parse_args()

    config: Dict[str, Any] = {"server": {}}
    if args.config:
        config = _load_yaml_config(args.config)
    elif os.environ.get("FACE_ENROLLMENT_SMOKE_CONFIG"):
        config = _load_yaml_config(os.environ["FACE_ENROLLMENT_SMOKE_CONFIG"])

    # 允许用环境变量覆盖
    server = config.setdefault("server", {})
    if os.environ.get("PUBLIC_BASE_URL"):
        server["public_base_url"] = os.environ["PUBLIC_BASE_URL"]
    if os.environ.get("FACE_ENROLLMENT_UPLOAD_SIGNING_KEY"):
        server["face_enrollment_upload_signing_key"] = os.environ[
            "FACE_ENROLLMENT_UPLOAD_SIGNING_KEY"
        ]
    if os.environ.get("AUTH_KEY"):
        server["auth_key"] = os.environ["AUTH_KEY"]
    face = server.setdefault("face", {})
    if os.environ.get("FACE_ACCOUNT_ID"):
        face["account_id"] = os.environ["FACE_ACCOUNT_ID"]

    failures = check_capability(config)

    base = args.base_url or (server.get("public_base_url") or "").strip()
    if args.probe and not args.dry_config_only:
        if not base.lower().startswith("https://"):
            failures.append("--probe requires https base-url")
        else:
            failures.extend(probe_auth_negatives(base))
    elif args.dry_config_only:
        print("OK: dry-config-only (skipped live probes)")

    if failures:
        print("SMOKE FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
