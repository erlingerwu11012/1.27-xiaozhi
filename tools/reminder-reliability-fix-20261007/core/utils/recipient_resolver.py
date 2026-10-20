"""家庭提醒收件人解析：仅信任网页 active profile 目录。

规则摘要：
- self / 空选择器：使用账号默认主人 usr_*（必须显式下发，不得留空）；
- explicit_name：仅当前 account 的 active 精确匹配（NFKC/trim/合并空白）；
- 关系词/代词：不可解析，追问；
- 可选 LLM 传入 recipient_person_id：必须重新验证属于当前 account 且 active；
- 旧 usr_* 永不自动指向同名新 profile；
- profiles HTTP 失败：fail-closed，不向设备发送必失败 MCP。
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

import aiohttp

from config.logger import setup_logging
from core.utils.account_identity import resolve_face_account_id
from core.utils.face_jwt import build_face_jwt_from_config, is_reserved_account_id

TAG = __name__
logger = setup_logging()

USR_ID_RE = re.compile(r"^(?:usr_[A-Za-z0-9]{4,64}|[A-Za-z0-9][A-Za-z0-9_-]{0,63}|all)$")

SELF_ALIASES = frozenset({"我", "自己", "本人", "俺", "咱", "咱们"})

RELATION_OR_PRONOUN = frozenset(
    {
        "儿子",
        "女儿",
        "妈妈",
        "妈",
        "母亲",
        "爸爸",
        "爸",
        "父亲",
        "老公",
        "老婆",
        "丈夫",
        "妻子",
        "爷爷",
        "奶奶",
        "外公",
        "外婆",
        "哥哥",
        "姐姐",
        "弟弟",
        "妹妹",
        "孩子",
        "小孩",
        "宝宝",
        "他",
        "她",
        "他们",
        "她们",
        "那个",
        "这个",
        "刚才的人",
        "那个人",
        "谁",
    }
)

IDENTITY_UNAVAILABLE_MSG = "账号身份正在同步，暂时无法创建提醒"
IDENTITY_UNAVAILABLE_CODE = "recipient_identity_unavailable"


class RecipientResultCode(str, Enum):
    SELF = "self"
    RESOLVED = "resolved"
    ALL = "all"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    RELATION_REFUSED = "relation_refused"
    INVALID_ID = "invalid_id"
    ACCOUNT_MISSING = "account_missing"
    DIRECTORY_ERROR = "directory_error"
    NEED_CLARIFY = "need_clarify"
    IDENTITY_UNAVAILABLE = "recipient_identity_unavailable"


@dataclass
class ProfileRecord:
    user_id: str
    display_name: str
    status: str = "active"
    account_id: str = ""
    is_default_owner: bool = False


@dataclass
class RecipientResolution:
    code: RecipientResultCode
    selector_type: str = ""
    recipient_person_id: Optional[str] = None
    recipient_display_name: Optional[str] = None
    message: str = ""
    # 是否应附带到设备 MCP（self 在有默认主人时也必须附带）
    attach_to_device: bool = False
    error_code: str = ""

    @property
    def ok_for_create(self) -> bool:
        if self.code == RecipientResultCode.ALL:
            return self.attach_to_device and self.recipient_person_id == "all"
        if self.code == RecipientResultCode.RESOLVED and self.attach_to_device:
            return bool(self.recipient_person_id) and bool(
                USR_ID_RE.match(self.recipient_person_id or "")
            )
        # 兼容旧 SELF：仅当已带合法 usr_* 时放行
        if self.code == RecipientResultCode.SELF:
            return bool(self.recipient_person_id) and bool(
                USR_ID_RE.match(self.recipient_person_id or "")
            ) and self.attach_to_device
        return False


def normalize_display_name(name: str) -> str:
    """与 face-api 一致：Unicode NFKC、trim、合并空白。"""
    if name is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(name)).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def is_self_selector(raw: str) -> bool:
    n = normalize_display_name(raw)
    return n in SELF_ALIASES


def is_relation_or_pronoun(raw: str) -> bool:
    n = normalize_display_name(raw)
    if not n:
        return False
    if n in RELATION_OR_PRONOUN:
        return True
    if n in {"他呀", "她呀", "那个家伙"}:
        return True
    return False


def classify_selector(raw: Optional[str]) -> str:
    """返回 self | explicit_name | relation | empty。"""
    if raw is None:
        return "empty"
    n = normalize_display_name(raw)
    if not n:
        return "empty"
    if is_self_selector(n):
        return "self"
    if is_relation_or_pronoun(n):
        return "relation"
    return "explicit_name"


@dataclass
class ProfileDirectory:
    """可测的人员目录抽象：内存列表或 face-api 拉取结果。"""

    account_id: str
    profiles: List[ProfileRecord] = field(default_factory=list)
    fetch_error: Optional[str] = None  # e.g. http_401 / network / account_missing

    def active_profiles(self) -> List[ProfileRecord]:
        return [
            p
            for p in self.profiles
            if (p.status or "active") == "active"
            and (not self.account_id or p.account_id in ("", self.account_id))
        ]

    def default_owner(self) -> Optional[ProfileRecord]:
        for p in self.active_profiles():
            if p.is_default_owner and USR_ID_RE.match(p.user_id or ""):
                return p
        return None

    def find_by_exact_name(self, name: str) -> List[ProfileRecord]:
        target = normalize_display_name(name)
        if not target:
            return []
        return [
            p
            for p in self.active_profiles()
            if normalize_display_name(p.display_name) == target
        ]

    def find_by_user_id(self, user_id: str) -> Optional[ProfileRecord]:
        uid = (user_id or "").strip()
        if not USR_ID_RE.match(uid):
            return None
        for p in self.active_profiles():
            if p.user_id == uid:
                return p
        return None


def _self_or_owner_resolution(directory: ProfileDirectory) -> RecipientResolution:
    if directory.fetch_error:
        return RecipientResolution(
            code=RecipientResultCode.IDENTITY_UNAVAILABLE,
            selector_type="self",
            message=IDENTITY_UNAVAILABLE_MSG,
            error_code=IDENTITY_UNAVAILABLE_CODE,
        )
    owner = directory.default_owner()
    if not owner:
        return RecipientResolution(
            code=RecipientResultCode.IDENTITY_UNAVAILABLE,
            selector_type="self",
            message=IDENTITY_UNAVAILABLE_MSG,
            error_code=IDENTITY_UNAVAILABLE_CODE,
        )
    return RecipientResolution(
        code=RecipientResultCode.RESOLVED,
        selector_type="self",
        recipient_person_id=owner.user_id,
        recipient_display_name=owner.display_name,
        message="",
        attach_to_device=True,
    )


def resolve_recipient(
    directory: ProfileDirectory,
    *,
    selector: Optional[str] = None,
    recipient_person_id: Optional[str] = None,
    default_self_when_empty: bool = True,
) -> RecipientResolution:
    """纯函数解析。account_id 必须已绑定到 directory。"""
    account_id = (directory.account_id or "").strip()
    if not account_id or is_reserved_account_id(account_id):
        return RecipientResolution(
            code=RecipientResultCode.ACCOUNT_MISSING,
            selector_type="unknown",
            message=IDENTITY_UNAVAILABLE_MSG,
            error_code=IDENTITY_UNAVAILABLE_CODE,
        )
    if directory.fetch_error:
        return RecipientResolution(
            code=RecipientResultCode.IDENTITY_UNAVAILABLE,
            selector_type="unknown",
            message=IDENTITY_UNAVAILABLE_MSG,
            error_code=IDENTITY_UNAVAILABLE_CODE,
        )

    # 1) 若 LLM 传入 person_id：必须重新验证，不可直接信任
    pid = (recipient_person_id or "").strip()
    if pid:
        if not USR_ID_RE.match(pid):
            return RecipientResolution(
                code=RecipientResultCode.INVALID_ID,
                selector_type="person_id",
                message="接收人标识无效，请使用网页已登记的姓名，或说「提醒我」。",
            )
        hit = directory.find_by_user_id(pid)
        if not hit:
            return RecipientResolution(
                code=RecipientResultCode.INVALID_ID,
                selector_type="person_id",
                message="接收人不是当前账户的有效用户，请改用网页已登记姓名。",
            )
        return RecipientResolution(
            code=RecipientResultCode.RESOLVED,
            selector_type="person_id",
            recipient_person_id=hit.user_id,
            recipient_display_name=hit.display_name,
            message="",
            attach_to_device=True,
        )

    kind = classify_selector(selector)
    if kind == "empty":
        if default_self_when_empty:
            return _self_or_owner_resolution(directory)
        return RecipientResolution(
            code=RecipientResultCode.NEED_CLARIFY,
            selector_type="empty",
            message="请说明提醒谁：可以说「我」，或使用网页已登记的明确姓名。",
        )

    if kind == "self":
        return _self_or_owner_resolution(directory)

    if kind == "relation":
        return RecipientResolution(
            code=RecipientResultCode.RELATION_REFUSED,
            selector_type="relation",
            message=(
                "我无法根据「儿子/妈妈/他/她」等关系词推断接收人。"
                "请改用「我」或网页里已登记的明确姓名。"
            ),
        )

    matches = directory.find_by_exact_name(selector or "")
    if len(matches) == 1:
        p = matches[0]
        return RecipientResolution(
            code=RecipientResultCode.RESOLVED,
            selector_type="explicit_name",
            recipient_person_id=p.user_id,
            recipient_display_name=p.display_name,
            message="",
            attach_to_device=True,
        )
    if len(matches) == 0:
        return RecipientResolution(
            code=RecipientResultCode.NOT_FOUND,
            selector_type="explicit_name",
            message="未找到该已登记姓名。请先在网页人脸管理中登记并启用，或改用「提醒我」。",
        )
    return RecipientResolution(
        code=RecipientResultCode.AMBIGUOUS,
        selector_type="explicit_name",
        message="姓名存在歧义，请在网页中处理重名或换用唯一名称后再试。",
    )


_RECIPIENT_ACTION = r"去|来|把|将|喝|吃|拿|看|做|记得|别|不要|该|买|交|写|开|关|睡|休息|起床|带|取|收|出门|运动|洗|打|给"


def extract_recipient_selector_from_text(text: str, known_names=()) -> Optional[str]:
    """Extract an explicit person, without treating the reminder action as a name."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(r"提醒(?:一下|下)?(我|自己|本人|俺)", raw)
    if m:
        return m.group(1)
    # Prefer an active directory name at the recipient position, including names
    # that happen to start with an action verb. Longest first avoids prefix names.
    names = sorted({normalize_display_name(n) for n in known_names if n}, key=len, reverse=True)
    for name in names:
        if re.search(r"提醒(?:一下|下)?" + re.escape(name)
                     + r"(?=" + _RECIPIENT_ACTION + r"|[，,。！!？?\s]|$)", raw):
            return name
    tail = re.search(r"提醒(?:一下|下)?(.*)", raw)
    # An omitted recipient is valid. Previously a terminal punctuation/$ branch
    # backtracked over '喝水哦' and produced a fictitious explicit name.
    if tail and re.match(r"(?:" + _RECIPIENT_ACTION + r")", tail.group(1)):
        return None
    m = re.search(
        r"提醒(?:一下|下)?([\u4e00-\u9fffA-Za-z0-9·]{1,12}?)"
        r"(?:" + _RECIPIENT_ACTION + r")",
        raw,
    )
    if m:
        name = m.group(1)
        if name not in {"一下", "下", "一下下"}:
            return name
    m = re.search(r"(?:给|帮)([\u4e00-\u9fffA-Za-z0-9·]{1,12}?)(?:设置|设|定|提)", raw)
    if m:
        return m.group(1)
    return None


def log_recipient_resolution(
    *,
    device_id: str,
    account_id: str,
    resolution: RecipientResolution,
    tool_name: str = "",
):
    payload = {
        "event": "recipient_resolve",
        "device_id": device_id or "",
        "account_id": account_id or "",
        "selector_type": resolution.selector_type,
        "result_code": resolution.code.value,
        "recipient_person_id": resolution.recipient_person_id or "",
        "error_code": resolution.error_code or "",
        "tool_name": tool_name,
    }
    logger.bind(tag=TAG).info(
        f"[recipient_resolver] {json.dumps(payload, ensure_ascii=False)}"
    )


def _profiles_url_from_identify(identify_url: str) -> str:
    base = (identify_url or "").rstrip("/")
    if base.endswith("/face/identify"):
        return base[: -len("/face/identify")] + "/face/profiles?status=active&ensure_owner=true"
    if "/face/" in base:
        root = base.split("/face/", 1)[0]
        return root + "/face/profiles?status=active&ensure_owner=true"
    return base + "/face/profiles?status=active&ensure_owner=true"


def _ensure_owner_url_from_identify(identify_url: str) -> str:
    base = (identify_url or "").rstrip("/")
    if base.endswith("/face/identify"):
        return base[: -len("/face/identify")] + "/face/accounts/ensure-owner"
    if "/face/" in base:
        root = base.split("/face/", 1)[0]
        return root + "/face/accounts/ensure-owner"
    return base + "/face/accounts/ensure-owner"


async def fetch_active_profiles(
    config: dict,
    *,
    device_id: str = "reminder",
    account_id: Optional[str] = None,
) -> ProfileDirectory:
    """从 face-api 拉取当前 account 的 active profiles，并确保默认主人存在。"""
    face_cfg = ((config or {}).get("server") or {}).get("face") or {}
    resolved = (account_id or "").strip() or resolve_face_account_id(config=config, allow_config_fallback=True) or ""
    if not resolved or is_reserved_account_id(resolved):
        return ProfileDirectory(
            account_id="", profiles=[], fetch_error="account_missing"
        )

    identify_url = (face_cfg.get("identify_url") or "").strip()
    profiles_url = (face_cfg.get("profiles_url") or "").strip()
    if profiles_url:
        if "ensure_owner=" not in profiles_url:
            sep = "&" if "?" in profiles_url else "?"
            profiles_url = f"{profiles_url}{sep}ensure_owner=true"
    else:
        if not identify_url:
            return ProfileDirectory(
                account_id=resolved, profiles=[], fetch_error="config_missing"
            )
        profiles_url = _profiles_url_from_identify(identify_url)

    token = build_face_jwt_from_config(
        config, account_id=resolved, device_id=device_id or "reminder"
    )
    if not token:
        logger.bind(tag=TAG).warning(
            "[recipient_resolver] face_jwt_unavailable account_set=1"
        )
        return ProfileDirectory(
            account_id=resolved, profiles=[], fetch_error="jwt_unavailable"
        )

    headers: Dict[str, str] = {"Authorization": f"Bearer {token}"}
    timeout = aiohttp.ClientTimeout(total=float(face_cfg.get("timeout", 2.0)))
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 显式 ensure-owner（与 list ?ensure_owner=true 双保险）
            ensure_url = _ensure_owner_url_from_identify(identify_url) if identify_url else ""
            if ensure_url:
                async with session.post(ensure_url, headers=headers) as ens:
                    if ens.status not in (200, 201):
                        logger.bind(tag=TAG).warning(
                            f"[recipient_resolver] ensure_owner_http={ens.status}"
                        )
                        return ProfileDirectory(
                            account_id=resolved,
                            profiles=[],
                            fetch_error=f"http_{ens.status}",
                        )
            async with session.get(profiles_url, headers=headers) as resp:
                if resp.status != 200:
                    logger.bind(tag=TAG).warning(
                        f"[recipient_resolver] profiles_http={resp.status}"
                    )
                    return ProfileDirectory(
                        account_id=resolved,
                        profiles=[],
                        fetch_error=f"http_{resp.status}",
                    )
                data = await resp.json()
    except Exception as exc:
        logger.bind(tag=TAG).warning(
            f"[recipient_resolver] profiles_fetch_failed err_type={type(exc).__name__}"
        )
        return ProfileDirectory(
            account_id=resolved, profiles=[], fetch_error="network"
        )

    items = data.get("profiles") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []

    profiles: List[ProfileRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uid = (item.get("user_id") or item.get("id") or "").strip()
        name = normalize_display_name(
            item.get("display_name") or item.get("name") or ""
        )
        status = (item.get("status") or "active").strip() or "active"
        if not uid or not USR_ID_RE.match(uid):
            continue
        if not name:
            name = "主人" if item.get("is_default_owner") else uid
        profiles.append(
            ProfileRecord(
                user_id=uid,
                display_name=name,
                status=status,
                account_id=resolved,
                is_default_owner=bool(item.get("is_default_owner")),
            )
        )
    return ProfileDirectory(account_id=resolved, profiles=profiles, fetch_error=None)


async def resolve_recipient_for_conn(
    conn,
    *,
    selector: Optional[str] = None,
    recipient_person_id: Optional[str] = None,
    user_text: str = "",
    tool_name: str = "",
    directory: Optional[ProfileDirectory] = None,
) -> RecipientResolution:
    """连接上下文解析入口。"""
    config = getattr(conn, "config", None) or {}
    account_id = resolve_face_account_id(conn=conn, config=config) or ""
    device_id = getattr(conn, "device_id", None) or (
        conn.headers.get("device-id", "") if getattr(conn, "headers", None) else ""
    )

    if directory is None:
        directory = await fetch_active_profiles(
            config, device_id=device_id or "reminder", account_id=account_id
        )

    sel = selector
    if not (sel or "").strip():
        sel = extract_recipient_selector_from_text(user_text)

    resolution = resolve_recipient(
        directory,
        selector=sel,
        recipient_person_id=recipient_person_id,
        default_self_when_empty=True,
    )
    log_recipient_resolution(
        device_id=device_id or "",
        account_id=account_id or directory.account_id,
        resolution=resolution,
        tool_name=tool_name,
    )
    return resolution


def apply_recipient_to_device_args(
    arguments: Dict[str, Any], resolution: RecipientResolution
) -> Dict[str, Any]:
    """将解析结果写入设备 MCP 参数；必须带合法 usr_*，禁止空/default/device_id。"""
    out = dict(arguments or {})
    out.pop("creator_person_id", None)
    # 与统一解析器一致：勿向旧固件下发 recipient_user_id
    out.pop("recipient_user_id", None)
    pid = (resolution.recipient_person_id or "").strip()
    if (
        resolution.attach_to_device
        and pid
        and USR_ID_RE.match(pid)
        and not is_reserved_account_id(pid)
    ):
        out["recipient_person_id"] = pid
        if resolution.recipient_display_name:
            out["recipient_display_name"] = resolution.recipient_display_name
        return out
    # fail-closed：不向设备下发空 recipient
    out.pop("recipient_person_id", None)
    out.pop("recipient_display_name", None)
    return out
