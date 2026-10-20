#!/usr/bin/env python3
"""提醒语音：独立合成 + ESP32-S3 风格下载 + 公网 HTTPS 通路探测。

不打印密钥 / token / 完整 URL query。
"""
from __future__ import annotations

import asyncio
import os
import ssl
import sys
import tempfile
import wave
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ESP32_UA = "ESP32 HTTP Client"
ESP32_DEVICE_ID = "b8:f8:62:7e:ca:58"


def _redact_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}?exp=***&device_id=***&sig=***"


def _huoshan_tts_config(config: dict) -> dict:
    """服务端全局配置通常不含 TTS；从设备智控台拉取。"""
    from config.manage_api_client import get_agent_models, init_service

    tts_cfg = {}
    try:
        init_service(config)
        models = get_agent_models(
            ESP32_DEVICE_ID,
            "e2e-reminder-voice-check",
            config.get("selected_module") or {},
        ) or {}
    except Exception:
        models = {}
    tts_block = models.get("TTS") or {}
    selected = (models.get("selected_module") or {}).get("TTS") or ""
    if selected and isinstance(tts_block.get(selected), dict):
        tts_cfg = tts_block.get(selected) or {}
    if not tts_cfg.get("ws_url"):
        for v in tts_block.values():
            if isinstance(v, dict) and v.get("type") == "huoshan_double_stream":
                tts_cfg = v
                break
    return tts_cfg


async def _synth_isolated(config: dict, script: str) -> bytes:
    from core.providers.tts.huoshan_double_stream import TTSProvider
    from core.utils.reminder_voice import synthesize_ogg_opus

    tts_cfg = _huoshan_tts_config(config)
    if not tts_cfg.get("access_token") or not tts_cfg.get("ws_url"):
        raise RuntimeError("huoshan_tts_config_missing")

    class _Conn:
        tts = TTSProvider(tts_cfg, delete_audio_file=True)

    return await synthesize_ogg_opus(_Conn(), script)


async def _local_esp32_download(ogg: bytes, signing: str) -> dict:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from core.api.reminder_voice_handler import ReminderVoiceHandler
    from core.utils.reminder_voice_store import ReminderVoiceStore, build_signed_url

    store = ReminderVoiceStore(ttl_sec=120)
    asset = store.put(ogg, device_id=ESP32_DEVICE_ID, account_id="acct_e2e")
    url, _exp = build_signed_url(
        public_base_url="https://api.realecho.cn",
        secret=signing,
        asset_id=asset.asset_id,
        device_id=ESP32_DEVICE_ID,
        ttl_sec=120,
    )
    q = parse_qs(urlparse(url).query)
    handler = ReminderVoiceHandler(
        {"server": {"reminder_voice_signing_key": signing, "face": {}}}
    )

    async def get_asset(request):
        from unittest.mock import patch

        with patch(
            "core.api.reminder_voice_handler.get_voice_store",
            return_value=store,
        ):
            return await handler.handle_get(request)

    app = web.Application()
    app.router.add_get("/reminder-voice/{asset_id}", get_asset)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        resp = await client.get(
            f"/reminder-voice/{asset.asset_id}",
            params={
                "exp": q["exp"][0],
                "device_id": q["device_id"][0],
                "sig": q["sig"][0],
            },
            headers={
                "Device-Id": ESP32_DEVICE_ID,
                "User-Agent": ESP32_UA,
                "Connection": "close",
                "Accept": "*/*",
            },
        )
        body = await resp.read()
        no_hdr = await client.get(
            f"/reminder-voice/{asset.asset_id}",
            params={
                "exp": q["exp"][0],
                "device_id": q["device_id"][0],
                "sig": q["sig"][0],
            },
            headers={"User-Agent": ESP32_UA},
        )
        return {
            "status": resp.status,
            "bytes": len(body),
            "ogg": body.startswith(b"OggS"),
            "content_type": resp.content_type,
            "no_device_id_status": no_hdr.status,
            "url_redacted": _redact_url(url),
        }
    finally:
        await client.close()


async def _public_https_probe() -> dict:
    import aiohttp

    url = (
        "https://api.realecho.cn/reminder-voice/"
        "0123456789abcdef0123456789abcdef"
        "?exp=1&device_id=b8:f8:62:7e:ca:58&sig=" + ("ab" * 32)
    )
    ctx = ssl.create_default_context()
    timeout = aiohttp.ClientTimeout(total=15)
    conn = aiohttp.TCPConnector(ssl=ctx, force_close=True)
    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as sess:
        async with sess.get(
            url,
            headers={
                "Device-Id": ESP32_DEVICE_ID,
                "User-Agent": ESP32_UA,
                "Connection": "close",
                "Accept": "*/*",
            },
        ) as resp:
            body = await resp.read()
            return {
                "https_ok": True,
                "tls": "tls",
                "status": resp.status,
                "body_len": len(body),
                "http_version": str(resp.version),
            }


def main() -> int:
    from config.config_loader import load_config
    from core.utils.reminder_voice_store import get_reminder_voice_signing_key

    report = {"steps": []}
    os.environ.setdefault("PYTHONUTF8", "1")
    config = load_config()
    signing = get_reminder_voice_signing_key(config)
    report["signing_key_present"] = bool(signing)
    report["public_base"] = (
        (config.get("server") or {}).get("public_base_url") or ""
    ).rstrip("/")

    async def _run():
        synth = {"ok": False}
        try:
            ogg = await _synth_isolated(config, "提醒你，该喝水了。")
            synth = {
                "ok": True,
                "bytes": len(ogg),
                "oggS": ogg.startswith(b"OggS"),
                "le16k": len(ogg) <= 16384,
            }
        except Exception as e:
            synth = {"ok": False, "err": type(e).__name__, "msg": str(e)[:160]}
            # 无火山时仍用最小合法 ogg 测下载协议
            ogg = b"OggS" + b"\x00" * 240
        report["synth"] = synth

        if not signing:
            report["download"] = {"ok": False, "err": "signing_key_missing"}
        else:
            report["download"] = await _local_esp32_download(ogg, signing)

        try:
            report["public_https"] = await _public_https_probe()
        except Exception as e:
            report["public_https"] = {
                "https_ok": False,
                "err": type(e).__name__,
                "msg": str(e)[:160],
            }

    asyncio.run(_run())

    print("=== reminder_voice e2e ===")
    print(f"public_base={report.get('public_base')}")
    print(f"signing_key_present={report.get('signing_key_present')}")
    print(f"synth={report.get('synth')}")
    print(f"esp32_download={report.get('download')}")
    print(f"public_https={report.get('public_https')}")
    download_ok = (report.get("download") or {}).get("status") == 200
    synth_ok = (report.get("synth") or {}).get("ok") is True
    https_ok = (report.get("public_https") or {}).get("https_ok") is True
    # 下载协议必须过；合成依赖火山，失败记入报告但不掩盖下载结论
    if download_ok and https_ok:
        return 0 if synth_ok else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
