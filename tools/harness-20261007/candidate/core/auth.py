import hmac
import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Optional, Tuple


class AuthenticationError(Exception):
    """认证异常；``code`` 为下发给设备的稳定错误码。"""

    def __init__(self, code: str = "invalid_token"):
        self.code = _normalize_auth_code(code)
        super().__init__(self.code)


# 允许出现在 close reason / JSON code 中的短枚举
AUTH_ERROR_CODES = frozenset(
    {
        "device_unbound",
        "device_disabled",
        "credential_revoked",
        "token_expired",
        "invalid_token",
    }
)

DEVICE_TOKEN_TTL_SECONDS = 700 * 24 * 60 * 60
TOKEN_VERSION_V2 = "v2"


def _normalize_auth_code(code: str) -> str:
    c = (code or "").strip()
    mapping = {
        "expired": "token_expired",
        "missing": "invalid_token",
        "malformed": "invalid_token",
        "invalid": "invalid_token",
        "auth_state_unavailable": "invalid_token",
        "credential_version_mismatch": "credential_revoked",
        "missing_authorization": "invalid_token",
        "missing_device_or_client_id": "invalid_token",
        "account_id_missing": "invalid_token",
        "invalid_token": "invalid_token",
        "token_expired": "token_expired",
        "device_unbound": "device_unbound",
        "device_disabled": "device_disabled",
        "credential_revoked": "credential_revoked",
        "unbound": "device_unbound",
        "disabled": "device_disabled",
        "active_mismatch": "credential_revoked",
    }
    out = mapping.get(c, c if c in AUTH_ERROR_CODES else "invalid_token")
    return out if out in AUTH_ERROR_CODES else "invalid_token"


@dataclass(frozen=True)
class TokenClaims:
    """本地验签通过后的声明（不含密钥/原文 token）。"""

    version: str  # "v1" | "v2"
    device_id: str  # normalized
    iat: int
    exp: int
    credential_version: Optional[int] = None


class AuthManager:
    """
    统一设备配对授权管理器（WSS / Reminder-Control / Face-Enrollment 共用）。

    v1（兼容至原 exp）::

        token      = base64url(hmac_sha256(secret, canonical)).rstrip('=') + "." + iat + "." + exp
        canonical  = normalized_device_id + "|" + iat + "|" + exp

    v2（新 OTA 签发，TTL=700 天）::

        token      = "v2." + sig + "." + iat + "." + exp + "." + credential_version
        canonical  = "v2|" + normalized_device_id + "|" + iat + "|" + exp + "|" + credential_version

    密钥与 manager-api ``server.secret`` / Python ``manager-api.secret`` 对齐。
    绝不记录 token / Authorization / 密钥明文。
    """

    def __init__(self, secret_key: str, expire_seconds: int = DEVICE_TOKEN_TTL_SECONDS):
        if not expire_seconds or expire_seconds < 0:
            self.expire_seconds = DEVICE_TOKEN_TTL_SECONDS
        else:
            self.expire_seconds = expire_seconds
        self.secret_key = secret_key

    @staticmethod
    def normalize_device_id(device_id: str) -> str:
        return (device_id or "").strip().lower().replace(":", "").replace("-", "")

    def _sign(self, content: str) -> str:
        sig = hmac.new(
            self.secret_key.encode("utf-8"), content.encode("utf-8"), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")

    def generate_token(
        self,
        client_id: str,
        username: str,
        expire_seconds: int = None,
        credential_version: int = 1,
    ) -> str:
        """生成 v2 token（测试/本地签发）。client_id 不参与签名。"""
        _ = client_id
        device_id = self.normalize_device_id(username)
        iat = int(time.time())
        ttl = expire_seconds if expire_seconds else self.expire_seconds
        exp = iat + int(ttl)
        ver = int(credential_version)
        content = f"{TOKEN_VERSION_V2}|{device_id}|{iat}|{exp}|{ver}"
        signature = self._sign(content)
        return f"{TOKEN_VERSION_V2}.{signature}.{iat}.{exp}.{ver}"

    def generate_v1_token(
        self, client_id: str, username: str, expire_seconds: int = None
    ) -> str:
        """仅测试：生成旧 v1 token。"""
        _ = client_id
        device_id = self.normalize_device_id(username)
        iat = int(time.time())
        ttl = expire_seconds if expire_seconds else 900
        exp = iat + int(ttl)
        content = f"{device_id}|{iat}|{exp}"
        signature = self._sign(content)
        return f"{signature}.{iat}.{exp}"

    def verify_token(self, token: str, client_id: str = None, username: str = None) -> bool:
        return self.verify_token_status(token, client_id, username) == "ok"

    def verify_token_status(
        self, token: str, client_id: str = None, username: str = None
    ) -> str:
        """本地 HMAC/exp 校验；v2 还需上层查 auth-state。返回 ok|expired|invalid|malformed|missing。"""
        claims, status = self.parse_and_verify(token, username=username)
        _ = client_id
        _ = claims
        return status

    def parse_and_verify(
        self, token: str, username: str = None
    ) -> Tuple[Optional[TokenClaims], str]:
        """
        返回 (claims|None, status)。
        status: ok | missing | malformed | expired | invalid
        """
        if not token:
            return None, "missing"
        parts = token.split(".")
        expected_device = self.normalize_device_id(username)

        # v2: v2.sig.iat.exp.cred_ver
        if len(parts) == 5 and parts[0] == TOKEN_VERSION_V2:
            try:
                _ver, signature, iat_s, exp_s, cred_s = parts
                iat = int(iat_s)
                exp = int(exp_s)
                cred_ver = int(cred_s)
            except (ValueError, AttributeError):
                return None, "malformed"
            if exp < int(time.time()):
                return None, "expired"
            content = f"{TOKEN_VERSION_V2}|{expected_device}|{iat}|{exp}|{cred_ver}"
            if not hmac.compare_digest(signature, self._sign(content)):
                return None, "invalid"
            return (
                TokenClaims(
                    version=TOKEN_VERSION_V2,
                    device_id=expected_device,
                    iat=iat,
                    exp=exp,
                    credential_version=cred_ver,
                ),
                "ok",
            )

        # v1: sig.iat.exp
        if len(parts) == 3:
            try:
                signature, iat_s, exp_s = parts
                iat = int(iat_s)
                exp = int(exp_s)
            except (ValueError, AttributeError):
                return None, "malformed"
            if exp < int(time.time()):
                return None, "expired"
            content = f"{expected_device}|{iat}|{exp}"
            if not hmac.compare_digest(signature, self._sign(content)):
                return None, "invalid"
            return (
                TokenClaims(
                    version="v1",
                    device_id=expected_device,
                    iat=iat,
                    exp=exp,
                    credential_version=None,
                ),
                "ok",
            )

        return None, "malformed"
