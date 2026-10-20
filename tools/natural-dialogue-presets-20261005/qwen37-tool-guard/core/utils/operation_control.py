"""Small, session-local action contract; never interpret model prose as execution.

Only unambiguous whole requests use the fast path. Everything else stays with the
primary model and its complete tool catalog. Pending slots are not persisted.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field

from plugins_func.register import Action, ActionResponse
from core.utils.remind_time import cn_num_to_int, extract_time_expression


CONTRACTS = {
    "volume": ("self_audio_speaker_set_volume", "volume", "音量"),
    "brightness": ("self_screen_set_brightness", "brightness", "亮度"),
    "status": ("self_get_device_status", None, "设备状态"),
    "preview_open": ("camera_open", None, "摄像头预览"),
    "preview_close": ("camera_close", None, "摄像头预览"),
    "photo": ("self_camera_take_photo", "question", "拍照"),
    "reminder": ("add_reminder", "text", "提醒"),
    "note": ("note_add", "text", "便签"),
    "world_time": ("get_world_time", "timezone", "世界时间查询"),
}
WORLD_TIMEZONES = {
    "东京": "Asia/Tokyo", "上海": "Asia/Shanghai", "北京": "Asia/Shanghai",
    "伦敦": "Europe/London", "巴黎": "Europe/Paris", "柏林": "Europe/Berlin",
    "纽约": "America/New_York", "洛杉矶": "America/Los_Angeles",
    "新加坡": "Asia/Singapore", "香港": "Asia/Hong_Kong", "首尔": "Asia/Seoul",
    "悉尼": "Australia/Sydney", "迪拜": "Asia/Dubai", "曼谷": "Asia/Bangkok",
}
CONTROL_NAMES = {row[0] for row in CONTRACTS.values()}
NUMBER = r"(?:\d{1,3}|一百|[零〇一二两三四五六七八九十]+)"
NON_COMMAND = re.compile(r"不要|别|不用|无需|不必|先不|暂不|不想|如果|假如|要是|假设|比如|例如|说过|他说|她说|有人说|是什么意思|是什么|会怎样|有什么用|怎么|如何|能不能|是否|吗|么|[‘’“”\"「」]|[<>]")


@dataclass
class Request:
    kind: str
    arguments: dict = field(default_factory=dict)
    delta: int | None = None
    prompt: str = ""


@dataclass
class Plan:
    requests: list[Request] = field(default_factory=list)
    reply: str = ""


def content_text(query):
    # Only extract content; speaker fields are not trusted identity.
    text = str(query or "").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and isinstance(obj.get("content"), str):
            return obj["content"].strip()
    except (ValueError, TypeError):
        pass
    return text


def ambiguous_clock(text):
    """12-hour clock needs a period; never silently infer AM/PM."""
    if re.search(r"上午|下午|早上|早晨|凌晨|中午|晚上|今晚|傍晚|24小时", text):
        return False
    m = re.search(r"([\d零〇一二两三四五六七八九十]+)(?:点|:|：)", text)
    n = cn_num_to_int(m[1]) if m else None
    return n is not None and 1 <= n <= 12


def day_hint(text):
    m = re.search(r"今天|明天|后天", text)
    return m[0] if m else ""


def conversation_only(text):
    """Whole, explicit greeting/style requests only; not keyword tool filtering."""
    s=re.sub(r'\s+','',text).strip('，,。.!！?？')
    return bool(re.fullmatch(
        r'(?:你好[呀啊]?[,，]?)?(?:随便聊聊|正常聊一会儿|我们正常聊一会儿|我们能正常聊一会儿吗|你好)'
        r'|你可以有幽默感[,，]?但别撒娇'
        r'|别哄我[,，]?说说你真实的看法'
        r'|我不喜欢你每句话都问我一个问题',s))


def parse_request(text):
    """A bounded positive grammar, not a bag of keyword triggers."""
    raw = text.strip(" ，,。.!！?？")
    s = re.sub(r"\s+", "", raw)
    s = re.sub(r"^(?:请|麻烦你?|帮我|帮忙|给我|替我)", "", s)
    s = re.sub(r"(?:吧|一下|就行|谢谢)$", "", s)
    # A question following a positive photo request is the VLM's question slot.
    photo = re.fullmatch(r"(?:拍照|拍一张(?:照片)?|拍张照片|拍张照)(?:[，,]?(.+))?", s)
    if (photo and (not photo[1] or re.match(r"看看|看下|看一下|描述|识别|告诉我|帮我看", photo[1]))
            and not re.search(r"(?:并|然后|再)(?:把|将|帮我|打开|关闭|查询|拍)", s)):
        return Request("photo", {"question": photo[1] or "描述一下看到的物品"}, prompt=raw)
    if not raw or NON_COMMAND.search(raw):
        return None
    world = re.fullmatch(r"(?:查询|查一下|查下|查|看看|看一下|查看|看)?(" + "|".join(WORLD_TIMEZONES)
                        + r")(?:现在|当前)?(?:的)?(?:时间|几点(?:钟)?)(?:了)?", s)
    if world:
        return Request("world_time", {"timezone": WORLD_TIMEZONES[world[1]]}, prompt=raw)
    for kind, noun in (("volume", r"(?:音量|声音)"), ("brightness", r"(?:屏幕亮度|亮度)")):
        key = CONTRACTS[kind][1]
        m = re.fullmatch(rf"(?:把|将)?{noun}(?:设置为|设置成|设为|设成|调到|调成|调至|调为|改成|改为|到|为|成|设置到|设到|调整到)({NUMBER})(?:%|％|百分比)?", s)
        if m:
            n = 100 if m[1] == "一百" else cn_num_to_int(m[1])
            return Request(kind, {key: n}, prompt=raw) if n is not None else None
        m = re.fullmatch(rf"(?:把|将)?{noun}(调高|调低|提高|降低|调亮|调暗|增加|减少)({NUMBER})?(?:格|点|%|％)?", s)
        if m:
            n = cn_num_to_int(m[2]) if m[2] else 10
            if n is None:
                return None
            sign = -1 if m[1] in {"调低", "降低", "调暗", "减少"} else 1
            return Request(kind, delta=sign*n, prompt=raw)
    if re.fullmatch(r"(?:打开|开启|开)(?:摄像头(?:预览)?|实时预览|实时画面)", s) or s in {"显示实时画面", "显示摄像头画面"}:
        return Request("preview_open", prompt=raw)
    if re.fullmatch(r"(?:关闭|关掉|关|停止|退出)(?:摄像头(?:预览)?|实时预览|预览)", s):
        return Request("preview_close", prompt=raw)
    if re.fullmatch(r"(?:查询|查|查看|看看|读一下|获取)?(?:一下)?(?:设备(?:当前|现在)?状态|当前设备状态|当前音量|当前亮度)", s):
        return Request("status", prompt=raw)
    # Repeating reminders have their own business path. Do not flatten them.
    if "每天" not in s and "每周" not in s:
        m = re.fullmatch(r"(.*?)提醒我(?:一下)?(.+)", s)
        if m:
            when = extract_time_expression(s)
            if not when:
                clock = re.fullmatch(r"(?:今天|明天|后天)?[\d零〇一二两三四五六七八九十]+点(?:半)?", m[1])
                when = clock[0] if clock else ''
            return Request("reminder", {"text": raw}, prompt=raw) if when and not ambiguous_clock(when) else Request("reminder", {"content": m[2], "day_hint": day_hint(s), "clock_hint": when}, prompt=raw)
    m = re.fullmatch(r"(?:记个便签|记一条便签|记一下|记下|记录一下)[：:]?(.+)", s)
    if m and not extract_time_expression(s) and "提醒" not in s:
        return Request("note", {"text": m[1], "remind_at": 0}, prompt=raw)
    return None


def actor_scope(conn):
    from core.utils.person_identity import current_turn
    actor = current_turn(conn)
    # Unknown speakers must not inherit a previous person's pending request.
    key = actor.key if actor else ("unknown", getattr(conn, "listen_epoch", 0))
    return (str(getattr(conn, "session_id", "")), key)


class OperationControl:
    def __init__(self):
        self.pending = None
        self.scope = None
        self.plan = Plan()
        self.ledger = {}
        self.last_kind = None
        self.last_scope = None
        self.last_at = 0.0
        self.blocked_names = set()
        self.force_answer = False
        self.chat_only = False
        self.explicit_targets = {}

    def begin(self, query, scope, now=None, has_recent_topic=False):
        now = time.monotonic() if now is None else now
        self.scope = scope
        self.ledger = {}
        self.plan = Plan()
        self.blocked_names = set()
        self.force_answer = False
        text = content_text(query)
        self.chat_only = conversation_only(text)
        self.query = text
        # Keep literal targets even when an extra conversational clause prevents
        # the bounded fast path. A model must not silently clamp 120 to 100.
        self.explicit_targets = {}
        for clause in re.split(r"[，,；;。]", text):
            request = parse_request(clause)
            if request and request.kind in {"volume", "brightness"} and request.delta is None:
                name, key, _ = CONTRACTS[request.kind]
                self.explicit_targets.setdefault(name, set()).add(request.arguments[key])
        if self.chat_only and not has_recent_topic and re.fullmatch(r'别哄我[，,]?说说你真实的看法[。]?',text):
            self.plan = Plan(reply='你想听哪件事的看法？')
            return self.plan
        positive_photo = parse_request(text)
        for clause in re.split(r"[，,；;。]", text):
          if NON_COMMAND.search(clause):
            subjects = {"volume": r"音量|声音", "brightness": r"亮度", "preview_open": r"摄像头|预览|实时画面", "preview_close": r"摄像头|预览", "photo": r"拍照|拍一张|照片", "reminder": r"提醒", "note": r"便签|记一下"}
            # Fast path deliberately declines mixed negation/command requests.
            # The model may answer, but cannot execute the named negated control.
            for kind, subject in subjects.items():
                if kind == 'photo' and positive_photo and positive_photo.kind == 'photo':
                    continue
                if re.search(subject, clause):
                    self.blocked_names.add(CONTRACTS[kind][0])
            if re.search(r'是什么|什么意思|如何|怎么',clause) and re.search(r'音量|亮度|设备状态',clause):
                self.blocked_names.add('self_get_device_status')
        if self.pending and (self.pending[0] != scope or now-self.pending[1] > 90):
            self.pending = None
        if self.pending:
            if re.fullmatch(r"(?:算了|取消|不用了|不设了|先不设|别设了)[。！!]?", text):
                self.pending = None
                self.plan = Plan(reply="好，这条提醒不创建。")
                return self.plan
            correction = re.fullmatch(
                rf'不是(?:上午|下午|晚上|早上)?{NUMBER}点(?:半)?[，,]?是((?:上午|下午|晚上|早上)?{NUMBER}点(?:半)?)[。]?', text)
            time_text = correction[1] if correction else text
            when = extract_time_expression(time_text)
            if not when and re.fullmatch(r"(?:改成|改为|就)?[\d零〇一二两三四五六七八九十]+点(?:半)?[。]?", text):
                when = re.sub(r"^(?:改成|改为|就)", "", text).strip("。")
            draft = self.pending[2]
            period_only = bool(not when and re.fullmatch(r"上午|下午|早上|晚上", text) and draft.get('clock_hint'))
            if period_only:
                when = text + re.sub(r"^(?:今天|明天|后天)", '', draft['clock_hint'])
            if correction and not when:
                when = time_text
            if when and (period_only or correction or re.fullmatch(r"(?:改成|改为|就)?"+re.escape(when)+r"(?:吧|。)?", text)):
                if ambiguous_clock(when):
                    draft['clock_hint'] = when
                    self.plan = Plan(reply="你说的是上午还是晚上？")
                    return self.plan
                if not day_hint(when) and draft.get('day_hint') and '后' not in when:
                    when = draft['day_hint'] + when
                self.pending = None
                self.plan = Plan([Request("reminder", {"content": draft['content'], "remind_time_str": when}, prompt=text)])
                return self.plan
            self.pending = None  # An unrelated topic must not complete an old draft.
        # Bare parameter corrections refer only to the last confirmed control.
        if self.last_scope == scope and now-self.last_at <= 90:
            if self.last_kind == 'preview_open' and re.fullmatch(r'关了吧[。]?',text):
                text = '关闭摄像头预览'
            elif self.last_kind == 'volume' and re.fullmatch(r'再小一点[。]?',text):
                text = '把音量调低10格'
            elif self.last_kind == 'brightness' and re.fullmatch(r'再(?:亮|暗)一点[。]?',text):
                text = '把亮度调高10格' if '亮' in text else '把亮度调低10格'
        if self.last_scope == scope and now-self.last_at <= 90 and self.last_kind in {"volume", "brightness"}:
            m = re.fullmatch(rf"(?:改成|改为|调到|还是)(?:{NUMBER})(?:%|％)?[。]?", text)
            if m:
                text = CONTRACTS[self.last_kind][2] + text.strip("。").replace("还是", "改成", 1)
        # Only fast-route if every clause is understood. Mixed free-form tasks go to LLM.
        clauses = [s for s in re.split(r"[，,；;。]|(?:并且|然后|并|再)(?=(?:把|将|帮我|查询|打开|关闭|拍))", text) if s.strip()]
        # Photo questions/reminder text are payload, not separate commands.
        whole = parse_request(text) if not re.search(r"(?:并|然后|再)(?:把|将|帮我|打开|关闭|查询)", text) else None
        requests = [whole] if whole else [parse_request(s) for s in clauses]
        if requests and all(requests):
            if len(requests) == 1 and requests[0].kind == "reminder" and "content" in requests[0].arguments and "remind_time_str" not in requests[0].arguments:
                draft = requests[0].arguments
                self.pending = (scope, now, dict(draft))
                self.plan = Plan(reply="你说的是上午还是晚上？" if ambiguous_clock(draft.get('clock_hint', '')) else "什么时候提醒你？")
            else:
                self.plan = Plan(requests)
        return self.plan

    def validate_intent(self, name, arguments):
        """Enforce contracts only for the positively recognized current request."""
        if self.chat_only:
            return "当前是在交流，没有请求工具操作，这次没有执行。"
        if name in self.blocked_names:
            return "这次是询问、引用或否定表达，没有执行这个操作。"
        if name == 'add_reminder' and not self.plan.requests and ambiguous_clock(self.query):
            return '提醒时间还缺上午或晚上，请先确认；这次没有创建提醒。'
        targets = self.explicit_targets.get(name)
        if targets:
            kind = next(k for k in ("volume", "brightness") if CONTRACTS[k][0] == name)
            key = CONTRACTS[kind][1]
            if arguments.get(key) not in targets:
                return "操作参数与用户明确的目标不一致，这次没有执行。"
        if name == "self_get_device_status" and any(r.delta is not None for r in self.plan.requests):
            return None
        if not self.plan.requests:
            return None
        matching = [r for r in self.plan.requests if CONTRACTS[r.kind][0] == name]
        if not matching:
            return "这个操作与本次请求不一致，没有执行。"
        for r in matching:
            if r.delta is not None or all(arguments.get(k) == v for k, v in r.arguments.items()):
                return None
        return "操作参数与本次请求不一致，没有执行。"


def get_control(conn):
    control = getattr(conn, "_operation_control", None)
    if control is None:
        control = OperationControl()
        conn._operation_control = control
    return control


def guard_reply(conn, text):
    """Covered operation claims need current-turn completion receipts before TTS."""
    if not enabled(conn):
        return text
    control = get_control(conn)
    if looks_like_text_tool_call(text):
        return "这次没有发出有效的工具调用，操作没有执行。"
    claims = {
        "volume": r"(?:音量|声音)(?:已经|已)(?:调|设|改)|(?:已经|已)(?:帮你|为你)?(?:把)?音量(?:调|设|改)",
        "brightness": r"亮度(?:已经|已)(?:调|设|改)|(?:已经|已)(?:帮你|为你)?(?:把)?(?:屏幕)?亮度(?:调|设|改)",
        "preview_open": r"摄像头(?:预览)?(?:已经|已)打开|(?:已经|已)(?:帮你|为你)?打开(?:了)?摄像头",
        "preview_close": r"摄像头(?:预览)?(?:已经|已)关闭|(?:已经|已)(?:帮你|为你)?关闭(?:了)?摄像头",
        "reminder": r"提醒(?:已经|已)(?:设好|设置好|创建)|(?:已经|已)(?:帮你|为你)?(?:设好|设置好)(?:了)?提醒",
        "note": r"便签(?:已经|已)(?:记下|创建|保存)|(?:已经|已)(?:帮你|为你)?记下(?:了)?便签",
    }
    for kind, pattern in claims.items():
        if re.search(pattern, text):
            name = CONTRACTS[kind][0]
            expected = [r.response for (tool, _), r in control.ledger.items()
                        if tool == name and r.action == Action.RESPONSE and r.response
                        and ("已调到" in r.response or "已打开" in r.response or "已关闭" in r.response
                             or "提醒已设好" in r.response or "便签已记下" in r.response)]
            if not expected:
                return "这次没有确认到操作完成的回执，不能说已经完成。"
    # Invalid stage labels must not leak to subtitle/history while the compiler
    # already excludes them from audio. Preserve ordinary [A]/[选项A] content.
    text = re.sub(r"\[(?:smirks?|smirking|winks?|grins?|chuckles?|tilts? head)\]", "", text, flags=re.I)
    from core.utils.textUtils import strip_display_emoji
    # Formatting only; no wording rewrite or second model.
    return strip_display_emoji(re.sub(r'[～~]+', '', text))


def looks_like_text_tool_call(text):
    """Detect transport-looking prose, never extract or execute its contents."""
    raw=str(text or '').strip()
    if re.search(r'<tool_call>|</tool_call>',raw):
        return True
    raw=re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    try:
        obj=json.loads(raw)
        rows = obj if isinstance(obj, list) else [obj]
        return any(isinstance(row, dict) and ('tool_calls' in row or 'function_call' in row
                   or ('name' in row and 'arguments' in row)
                   or (row.get('type') == 'function' and 'function' in row)) for row in rows)
    except (ValueError,TypeError):
        pass
    return False


class SpeechBuffer:
    """Stream checked complete sentences when no tools are offered.

    Hold JSON/XML-looking output intact so an unfinished envelope cannot leak to
    audio. Delivered text is also the history/caption source.
    """
    def __init__(self,conn):
        self.conn=conn;self.pending='';self.delivered=[]

    def feed(self,chunk,final=False):
        self.pending+=str(chunk or '')
        if not final and (self.pending.lstrip().startswith(('{','[','<','`'))):
            return []
        if final:
            units=[self.pending] if self.pending else []
            self.pending=''
        else:
            units=[]
            while True:
                match=re.search(r'[。！？!?](?:[”」])?',self.pending)
                if not match:break
                units.append(self.pending[:match.end()]);self.pending=self.pending[match.end():]
        out=[guard_reply(self.conn,unit) for unit in units]
        self.delivered.extend(out)
        return out


def enabled(conn):
    cfg = (getattr(conn, "config", {}) or {}).get("operation_control", {})
    return isinstance(cfg, dict) and cfg.get("enabled", False) is True


def payload_of(result):
    value = getattr(result, "result", None)
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


def feedback(request, result):
    """A completion is a business receipt, not a successful transport envelope."""
    body = payload_of(result)
    if getattr(result, "action", None) in {Action.ERROR, Action.NOTFOUND, Action.RESPONSE}:
        return str(result.response or "这次操作没有完成。")
    if isinstance(body, dict):
        if body.get("ok") is False or body.get("success") is False or body.get("status") == "error":
            return "这次操作没有完成。"
        if body.get("accepted") is True or body.get("state") in {"accepted", "queued", "running", "starting"}:
            return "请求已被接收，还不能确认完成。"
    if request.kind in {"volume", "brightness"}:
        key = CONTRACTS[request.kind][1]
        target = request.arguments.get(key)
        if isinstance(body, dict) and body.get("ok") is True and type(body.get(key)) is int and body[key] == target:
            return f"{CONTRACTS[request.kind][2]}已调到{target}。"
        return f"还不能确认{CONTRACTS[request.kind][2]}是否调整成功。"
    if request.kind in {"preview_open", "preview_close"}:
        target = "open" if request.kind == "preview_open" else "closed"
        if isinstance(body, dict) and body.get("state") == target and body.get("ok") is True:
            return "摄像头预览已打开。" if target == "open" else "摄像头预览已关闭。"
        return "还不能确认摄像头预览状态。"
    if request.kind == "note":
        if str(getattr(result, "result", "")).startswith("已记录："):
            return "便签已记下。"
        if isinstance(body, dict) and type(body.get("id")) is int and body["id"] >= 0 and body.get("status") == "created":
            return "便签已记下。"
        return "还不能确认便签是否创建成功。"
    if request.kind == "reminder":
        # Device reminder interceptor marks this only after a verified create receipt.
        if getattr(result, "operation_state", None) == "completed":
            return "提醒已设好。"
        return str(result.response or "提醒尚未确认创建成功。")
    return None  # Read-only status and VLM answers still use the primary model.


async def execute_plan(conn, plan):
    control = get_control(conn)
    results = []
    messages = []
    manager = conn.func_handler.tool_manager
    for request in plan.requests:
        name, key, label = CONTRACTS[request.kind]
        if not manager.has_tool(name):
            messages.append(f"这台设备目前不支持{label}。")
            continue
        arguments = dict(request.arguments)
        if request.delta is not None:
            if not manager.has_tool("self_get_device_status"):
                messages.append(f"无法读取当前{label}，请直接说要调到多少。")
                continue
            status = await manager.execute_tool("self_get_device_status", {})
            body = payload_of(status)
            # Firmware status nests output_volume under audio_speaker.
            value = body.get(key) if isinstance(body, dict) else None
            if value is None and isinstance(body, dict):
                sub = body.get("audio_speaker" if key == "volume" else "screen", {})
                value = sub.get("volume" if key == "volume" else "brightness") if isinstance(sub, dict) else None
                if value is None and key == "volume" and isinstance(sub, dict):
                    value = sub.get("output_volume")
            if type(value) is not int or status.action in {Action.ERROR, Action.RESPONSE, Action.NOTFOUND}:
                messages.append(f"没有读到当前{label}，这次没有调整。")
                continue
            schema = manager.get_all_tools()[name].description["function"]["parameters"]["properties"].get(key, {})
            lo, hi = schema.get("minimum", 0), schema.get("maximum", 100)
            arguments[key] = max(lo, min(hi, value+request.delta))
        # Record exact resolved arguments before the manager's intent gate.
        request.arguments = arguments
        request.delta = None
        call = {"id": "operation_"+str(len(results)), "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}
        result = await conn.func_handler.handle_llm_function_call(conn, call)
        response = feedback(request, result)
        if response is None:
            results.append((result, call))
        else:
            messages.append(response)
            if response.endswith("。") and ("已调到" in response or response in {'摄像头预览已打开。','摄像头预览已关闭。'}):
                control.last_kind, control.last_scope, control.last_at = request.kind, control.scope, time.monotonic()
    return messages, results
