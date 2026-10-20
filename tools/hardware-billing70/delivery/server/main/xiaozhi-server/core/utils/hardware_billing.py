"""Xiaozhi-only billing proof. No Aimi routes, wallet or headers are used here.

The product account is supplied by authenticated server configuration. It must
never come from model tool arguments, ASR text, or a device-provided user id.
"""
import hashlib
import hmac
import os
import time
import uuid
from urllib.parse import urlsplit

ALLOWED_OPERATIONS = {"llm", "summary", "habit", "vision", "asr", "tts",
                      "fact_add", "search", "storage_item_hour"}

def request_headers(account_id, operation, request_id=None):
    account = str(account_id or "")
    if not account.isdigit() or operation not in ALLOWED_OPERATIONS:
        raise ValueError("hardware billing requires a trusted account and operation")
    return {"X-HW-Account": account, "X-HW-Operation": operation,
            "X-HW-Request-ID": request_id or uuid.uuid4().hex}

def sign_request(request, origin_variable="HW_BILLING_GATEWAY_ORIGIN"):
    """httpx request hook: sign the actual serialized bytes produced by the SDK.

    A logical request id persists across SDK retries; timestamp/signature refresh
    without changing that id. Gateway idempotency must reject a second dispatch.
    """
    account = request.headers.get("X-HW-Account", "")
    if not account:
        raise ValueError("hardware billing account is missing")
    operation = request.headers.get("X-HW-Operation", "")
    request_id = request.headers.get("X-HW-Request-ID", "")
    if not account.isdigit() or operation not in ALLOWED_OPERATIONS or not request_id:
        raise ValueError("invalid hardware billing context")
    key = os.environ.get("HW_BILLING_SERVICE_KEY", "").encode("utf-8")
    gateway = os.environ.get(origin_variable, "")
    if len(key) < 32 or not gateway:
        raise ValueError("hardware billing service authentication is not configured")
    expected, actual = urlsplit(gateway), urlsplit(str(request.url))
    if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise ValueError("hardware billing request is outside its gateway")
    stamp = str(int(time.time()))
    path = actual.path + ("?" + actual.query if actual.query else "")
    body_hash = hashlib.sha256(request.content).hexdigest()
    fields = [request.method, path, body_hash, stamp, request_id, account, operation]
    if any("\n" in x or "\r" in x for x in fields):
        raise ValueError("invalid hardware billing proof field")
    signature = hmac.new(key, "\n".join(fields).encode(), hashlib.sha256).hexdigest()
    request.headers["X-HW-Timestamp"] = stamp
    request.headers["X-HW-Signature"] = signature

def provider_context(config):
    """Reject accidental hardware/Aimi mixing before any outbound request."""
    if not config.get("hardware_billing"):
        return None
    if config.get("aimi_device_gateway"):
        raise ValueError("hardware and Aimi billing cannot be enabled together")
    account = config.get("hardware_account_id")
    operation = config.get("hardware_operation", "llm")
    request_headers(account, operation)  # validation only
    model = config.get("model_name") or config.get("model", "")
    allowed = {"qwen-plus": {"llm", "summary", "habit"},
               "qwen3-vl-flash": {"vision"},
               "qwen3-asr-flash-realtime": {"asr"},
               "qwen-audio-3.0-tts-plus": {"tts"}}
    if operation not in allowed.get(model, set()):
        raise ValueError("unverified hardware model")
    return {"account_id": str(account), "operation": operation}

def websocket_headers(url, config, headers):
    """Sign each fresh audio socket; no credentials may leave its configured origin."""
    context = provider_context(config)
    if context is None:
        return dict(headers)
    from types import SimpleNamespace
    parts = urlsplit(url)
    if parts.scheme not in {"ws", "wss"} or parts.username or parts.password:
        raise ValueError("invalid hardware audio gateway")
    from urllib.parse import parse_qs
    if parse_qs(parts.query).get("model") != [config.get("model_name") or config.get("model")]:
        raise ValueError("hardware audio model must be bound to the signed URL")
    http_url = ("https" if parts.scheme == "wss" else "http") + "://" + parts.netloc + parts.path
    if parts.query:
        http_url += "?" + parts.query
    signed = dict(headers)
    signed.update(request_headers(context["account_id"], context["operation"]))
    request = SimpleNamespace(url=http_url, method="GET", content=b"", headers=signed)
    sign_request(request, "HW_BILLING_AUDIO_GATEWAY_ORIGIN")
    return signed
