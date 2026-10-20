import httpx
import openai
import uuid
import time
import threading
from openai.types import CompletionUsage
from config.logger import setup_logging
from core.utils.util import check_model_key
from core.providers.llm.base import LLMProviderBase
from core.utils import trace_log as trace
from core.utils.hardware_billing import provider_context, request_headers, sign_request

TAG = __name__
logger = setup_logging()


class LLMProvider(LLMProviderBase):
    def __init__(self, config):
        self.hardware_context = provider_context(config)
        self.model_name = config.get("model_name")
        self.api_key = config.get("api_key")
        # 配置来源标识（模块名），用于 401 可观测；绝不打印 key
        self.provider_config_name = (
            config.get("_config_name")
            or config.get("name")
            or config.get("model_name")
            or "openai_compatible"
        )
        self.provider_type = config.get("type") or "openai"
        if "base_url" in config:
            self.base_url = config.get("base_url")
        else:
            self.base_url = config.get("url")
        timeout = config.get("timeout", 300)
        self.timeout = int(timeout) if timeout else 300
        self.aimi_device_gateway = bool(config.get("aimi_device_gateway", False))
        self.aimi_device_service_key = config.get("aimi_device_service_key", "")
        self._aimi_device_contexts = {}
        self._usage_local = threading.local()
        self.last_usage = None
        self.input_limit_tokens = config.get("input_limit_tokens")
        self.context_limit_tokens = config.get("context_limit_tokens")
        if self.model_name == "qwen-plus":
            self.input_limit_tokens = self.input_limit_tokens or 997952
            self.context_limit_tokens = self.context_limit_tokens or 1000000
        elif self.model_name in {"qwen3.7-plus", "qwen3.8-flash", "qwen3.8-max"}:
            self.input_limit_tokens = self.input_limit_tokens or 991808
            self.context_limit_tokens = self.context_limit_tokens or 1000000

        param_defaults = {
            "max_tokens": int,
            "temperature": lambda x: round(float(x), 1),
            "top_p": lambda x: round(float(x), 1),
            "top_k": int,
            "frequency_penalty": lambda x: round(float(x), 1),
        }

        for param, converter in param_defaults.items():
            value = config.get(param)
            try:
                setattr(
                    self,
                    param,
                    converter(value) if value not in (None, "") else None,
                )
            except (ValueError, TypeError):
                setattr(self, param, None)

        logger.debug(
            f"意图识别参数初始化: {self.temperature}, {self.max_tokens}, {self.top_p}, {self.top_k}, {self.frequency_penalty}"
        )

        model_key_msg = check_model_key("LLM", self.api_key)
        if model_key_msg:
            logger.bind(tag=TAG).error(model_key_msg)
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            http_client=httpx.Client(
                timeout=httpx.Timeout(self.timeout),
                headers={"Accept-Charset": "utf-8"},
                default_encoding="utf-8",
                event_hooks={"request": [sign_request]} if self.hardware_context else None,
            ),
        )

    @property
    def last_usage(self):
        return getattr(self._usage_local, "value", None)

    @last_usage.setter
    def last_usage(self, value):
        self._usage_local.value = value

    def set_aimi_device_context(self, context):
        if self.aimi_device_gateway:
            self._aimi_device_contexts[context["session_id"]] = dict(context)

    def _aimi_headers(self, session_id):
        if not self.aimi_device_gateway:
            return None
        context = self._aimi_device_contexts.get(session_id)
        if not context or not self.aimi_device_service_key:
            raise ValueError("AIMI device gateway requires device context and service key")
        return {
            "X-AIMI-Device-Service-Key": self.aimi_device_service_key,
            "X-AIMI-Device-ID": context["device_id"],
            "X-AIMI-Device-MAC": context.get("mac_address", ""),
            "X-AIMI-Xiaozhi-User-ID": context.get("user_id", ""),
            "X-AIMI-Device-Session-ID": context["session_id"],
            "X-Request-ID": f"xiaozhi-{session_id}-{uuid.uuid4().hex}",
        }

    @staticmethod
    def normalize_dialogue(dialogue):
        """自动修复 dialogue 中缺失 content 的消息"""
        for msg in dialogue:
            if "role" in msg and "content" not in msg:
                msg["content"] = ""
        return dialogue

    def _create_with_retry(self, **request_params):
        """
        带重试的 API 调用。遇到可重试错误（429/500/502/503/超时）时，
        指数退避重试最多 2 次。上下文超限等不可重试错误直接抛出。
        """
        import time as _time

        max_retries = 2
        base_delay = 1.0  # 秒

        for attempt in range(max_retries + 1):
            try:
                return self.client.chat.completions.create(**request_params)
            except Exception as e:
                err_str = str(e).lower()
                # 上下文超限等语义错误不重试，直接抛出
                is_context_error = any(kw in err_str for kw in [
                    "context_length", "context length", "too long",
                    "too many tokens", "maximum context", "reduce the length",
                    "reduce your prompt", "invalid", "authentication",
                ])
                if is_context_error:
                    raise

                # 可重试的错误：限流、服务端故障、超时
                is_retryable = any(kw in err_str for kw in [
                    "429", "rate limit", "rate_limit",
                    "500", "502", "503", "bad gateway", "service unavailable",
                    "timeout", "timed out", "connection",
                ])

                if is_retryable and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)  # 1s, 2s
                    logger.bind(tag=TAG).warning(
                        f"LLM API 可重试错误（第 {attempt + 1} 次），{delay}s 后重试: {e}"
                    )
                    _time.sleep(delay)
                    continue

                # 不可重试或已用完重试次数
                raise

    def _endpoint_meta(self):
        return {
            "provider": self.provider_type,
            "provider_config_name": self.provider_config_name,
            "model": self.model_name,
            "base_url": self.base_url,
        }

    def _maybe_include_stream_usage(self, request_params, conn):
        """include_stream_usage 观测开关：流式请求时显式要求上游返回 usage。

        仅在 llm_observability.include_stream_usage=true 时启用；缺失由
        上游决定，不在此兜底。参数失败不得导致重复工具执行或重复播放。

        若上游已确认不支持 stream_options（曾返回 400），自动降级关闭，
        后续轮次不再发送，避免每轮 400 且绝不重放本轮请求。
        """
        try:
            if getattr(self, "_stream_usage_unsupported", False):
                return
            if not request_params.get("stream", False):
                return
            if conn is None:
                return
            from core.utils.prompt_pipeline import include_stream_usage

            if include_stream_usage(conn):
                request_params["stream_options"] = {"include_usage": True}
        except Exception:
            # 观测开关失败绝不影响主链路
            return

    def _detect_stream_usage_unsupported(self, exc) -> bool:
        """探测 stream_options 是否被上游拒绝；一旦确认，连接内自动降级关闭。"""
        err = str(exc).lower()
        if "stream_options" not in err and "include_usage" not in err:
            return False
        if not getattr(self, "_stream_usage_unsupported", False):
            self._stream_usage_unsupported = True
            trace.emit(
                "llm.stream_usage_unsupported",
                trace.current_conn(),
                {**self._endpoint_meta(), "error": str(exc)[:200]},
            )
        return True

    def _trace_request(self, conn, session_id, request_params, kind):
        sent_keys = sorted(request_params.keys())
        missing = []
        for name in ("tool_choice", "stream_options", "user"):
            if name not in request_params:
                missing.append(name)
        trace.emit(
            "llm.request",
            conn,
            {
                **self._endpoint_meta(),
                "kind": kind,
                "session_id_arg": session_id,
                "sent_keys": sent_keys,
                "not_sent": missing,
                "request": request_params,
                "stream": request_params.get("stream"),
            },
        )

    def _usage_from_chunk(self, chunk):
        usage = getattr(chunk, "usage", None)
        if usage is None:
            return None, True
        dumped = trace.dump_obj(usage)
        return dumped, False

    @staticmethod
    def _cached_tokens(usage):
        """从 usage 中提取 prompt_tokens_details.cached_tokens（可能缺失）。"""
        if not isinstance(usage, dict):
            return None
        details = usage.get("prompt_tokens_details")
        if not isinstance(details, dict):
            return None
        ct = details.get("cached_tokens")
        if ct is not None:
            return ct
        return None

    def response(self, session_id, dialogue, **kwargs):
        try:
            self.last_usage = None
            dialogue = self.normalize_dialogue(dialogue)

            request_params = {
                "model": self.model_name,
                "messages": dialogue,
                "stream": not self.aimi_device_gateway,
            }
            if self.model_name in {"qwen3.7-plus", "qwen3.8-flash", "qwen3.8-max"}:
                request_params["extra_body"] = {"enable_thinking": False, "preserve_thinking": False}
            if self.hardware_context:
                request_params.setdefault("extra_body", {})["enable_thinking"] = False
                request_params["extra_headers"] = request_headers(
                    self.hardware_context["account_id"],
                    kwargs.get("billing_operation", self.hardware_context["operation"]))
                request_params["stream_options"] = {"include_usage": True}
            if self.aimi_device_gateway:
                request_params["extra_headers"] = self._aimi_headers(session_id)

            # 添加可选参数,只有当参数不为None时才添加
            optional_params = {
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "temperature": kwargs.get("temperature", self.temperature),
                "top_p": kwargs.get("top_p", self.top_p),
                "top_k": kwargs.get("top_k", self.top_k),
                "frequency_penalty": kwargs.get("frequency_penalty", self.frequency_penalty),
            }

            for key, value in optional_params.items():
                if value is not None:
                    request_params[key] = value

            conn = trace.current_conn()
            self._maybe_include_stream_usage(request_params, conn)
            t_start = time.monotonic()
            trace.mark(conn, "llm_start")
            self._trace_request(conn, session_id, request_params, "response")
            responses = self._create_with_retry(**request_params)

            if self.aimi_device_gateway:
                dumped = trace.dump_obj(responses)
                usage, usage_missing = self._usage_from_chunk(responses)
                self.last_usage = usage
                trace.emit(
                    "llm.response",
                    conn,
                    {
                        **self._endpoint_meta(),
                        "kind": "non_stream",
                        "chunk": dumped,
                        "usage": usage,
                        "usage_missing": usage_missing,
                        "upstream_request_id": getattr(responses, "id", None)
                        or (dumped.get("id") if isinstance(dumped, dict) else None),
                        "elapsed_ms": round((time.monotonic() - t_start) * 1000.0, 3),
                    },
                )
                content = responses.choices[0].message.content if responses.choices else ""
                if content:
                    yield content
                return

            is_active = True
            first = True
            usage_seen = False
            cached_tokens = None
            last_finish = None
            upstream_id = None
            for chunk in responses:
                dumped = trace.dump_obj(chunk)
                if isinstance(dumped, dict) and dumped.get("id") and not upstream_id:
                    upstream_id = dumped.get("id")
                usage, usage_missing = self._usage_from_chunk(chunk)
                if usage is not None:
                    usage_seen = True
                    self.last_usage = usage
                    ct = self._cached_tokens(usage)
                    if ct is not None:
                        cached_tokens = ct
                try:
                    delta = chunk.choices[0].delta if getattr(chunk, "choices", None) else None
                    content = getattr(delta, "content", "") if delta else ""
                    finish_reason = getattr(chunk.choices[0], "finish_reason", None) if getattr(chunk, "choices", None) else None
                    if finish_reason:
                        last_finish = finish_reason
                except IndexError:
                    content = ""
                    finish_reason = None
                trace.emit(
                    "llm.chunk",
                    conn,
                    {
                        **self._endpoint_meta(),
                        "chunk": dumped,
                        "usage": usage,
                        "usage_missing": usage_missing,
                        "finish_reason": finish_reason,
                    },
                )
                if content:
                    if first:
                        first = False
                        trace.mark(conn, "llm_first_token")
                    if "<think>" in content:
                        is_active = False
                        content = content.split("<think>")[0]
                    if "</think>" in content:
                        is_active = True
                        content = content.split("</think>")[-1]
                    if is_active:
                        yield content

            trace.emit(
                "llm.done",
                conn,
                {
                    **self._endpoint_meta(),
                    "first_token_ms": trace.latency_ms(conn, "llm_start", "llm_first_token"),
                    "elapsed_ms": round((time.monotonic() - t_start) * 1000.0, 3),
                    "usage_missing": not usage_seen,
                    "prompt_tokens": (self.last_usage or {}).get("prompt_tokens", "unknown"),
                    "completion_tokens": (self.last_usage or {}).get("completion_tokens", "unknown"),
                    "cached_tokens": cached_tokens if cached_tokens is not None else "unknown",
                    "finish_reason": last_finish,
                    "upstream_request_id": upstream_id,
                },
            )

        except Exception as e:
            from core.utils.context_window import ContextLimitError, is_context_limit
            self._usage_local.error = {"type":type(e).__name__,"status":getattr(e,"status_code",None),"code":getattr(e,"code",None)}
            if is_context_limit(e):
                raise ContextLimitError("upstream_context_limit") from e
            self._detect_stream_usage_unsupported(e)
            host = ""
            try:
                from urllib.parse import urlparse

                host = urlparse(self.base_url or "").netloc or ""
            except Exception:
                host = ""
            logger.bind(tag=TAG).error(
                f"Error in response generation: provider={self.provider_config_name} "
                f"type={self.provider_type} model={self.model_name} host={host} "
                f"config_key=LLM.{self.provider_config_name}.api_key err={e}"
            )
            trace.emit(
                "llm.error",
                trace.current_conn(),
                {**self._endpoint_meta(), "error_type": type(e).__name__, "error": str(e)},
            )
            # 不关闭 WebSocket；向上层产出安全降级文本
            yield "【服务暂时无法响应，请稍后再试】"

    def decision(self, messages):
        """One bounded structured decision through the existing signed gateway."""
        import json
        from core.utils.tool_harness.models import Decision
        parameters={'model':self.model_name,'messages':messages,'stream':False,
                    'temperature':self.temperature,'max_tokens':1800,
                    # This gateway accepts JSON Schema, but repeated real
                    # operation probes corrupted keys in unconstrained argument
                    # objects. Use JSON mode and enforce the full contract locally.
                    'response_format':{'type':'json_object'},
                    'extra_body':{'enable_thinking':False,'preserve_thinking':False}}
        if self.hardware_context:
            parameters['extra_headers']=request_headers(self.hardware_context['account_id'],self.hardware_context['operation'])
        response=self.client.with_options(max_retries=0,timeout=45).chat.completions.create(**parameters)
        self.last_usage=response.usage.model_dump() if response.usage else None
        message=response.choices[0].message
        if getattr(message,'tool_calls',None):raise ValueError('unexpected_native_calls_in_decision')
        if response.choices[0].finish_reason!='stop':raise ValueError('incomplete_decision')
        return json.loads(message.content)

    def decision_stream(self,messages,on_reply=None,admit_reply=None):
        """Consume real network chunks; control metadata gates incremental speech."""
        from core.utils.tool_harness.stream_decision import ReplyStream
        from core.utils.tool_harness.models import Decision
        # Omitted optional fields have their declared local defaults. Reply is
        # terminal, so no later field may change those controls.
        required={'mode','steps','authorized_writes'}
        def admit(meta):
            if not required<=set(meta):return False
            try:draft=Decision.model_validate(dict(meta,reply='待确认'))
            except Exception:return False
            return draft.mode in {'chat','clarify'} and not draft.steps and not draft.authorized_writes and (admit_reply is None or admit_reply(draft))
        parser=ReplyStream(on_reply,admit)
        params={'model':self.model_name,'messages':messages,'stream':True,
                'stream_options':{'include_usage':True},'temperature':self.temperature,
                'max_tokens':1800,'response_format':{'type':'json_object'},
                'extra_body':{'enable_thinking':False,'preserve_thinking':False}}
        if self.hardware_context:params['extra_headers']=request_headers(self.hardware_context['account_id'],self.hardware_context['operation'])
        self.last_usage=None
        started=time.monotonic();first=None;finish=None;chunks=0
        stream=self.client.with_options(max_retries=0,timeout=45).chat.completions.create(**params)
        try:
            for chunk in stream:
                chunks+=1
                if chunk.usage:self.last_usage=chunk.usage.model_dump()
                if not chunk.choices:continue
                choice=chunk.choices[0]
                if getattr(choice.delta,'tool_calls',None):raise ValueError('unexpected_native_calls_in_decision')
                if choice.delta.content:
                    if first is None:first=time.monotonic()-started
                    parser.feed(choice.delta.content)
                if choice.finish_reason:finish=choice.finish_reason
            if finish!='stop':raise ValueError('incomplete_decision')
            return parser.finish()
        finally:
            stream.close()
            self.last_decision_timing={'network_chunks':chunks,'first_delta_seconds':first,'total_seconds':time.monotonic()-started}

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        try:
            self.last_usage = None
            dialogue = self.normalize_dialogue(dialogue)

            request_params = {
                "model": self.model_name,
                "messages": dialogue,
                "stream": not self.aimi_device_gateway,
                "tools": functions,
            }
            if functions and kwargs.get('tool_choice') is not None:
                request_params['tool_choice'] = kwargs['tool_choice']
            if kwargs.get('response_format') is not None:
                request_params['response_format'] = kwargs['response_format']
            if self.model_name in {"qwen3.7-plus", "qwen3.8-flash", "qwen3.8-max"}:
                request_params["extra_body"] = {"enable_thinking": False, "preserve_thinking": False}
            if self.hardware_context:
                request_params.setdefault("extra_body", {})["enable_thinking"] = False
                request_params["extra_headers"] = request_headers(
                    self.hardware_context["account_id"],
                    kwargs.get("billing_operation", self.hardware_context["operation"]))
                request_params["stream_options"] = {"include_usage": True}
            if self.aimi_device_gateway:
                request_params["extra_headers"] = self._aimi_headers(session_id)

            optional_params = {
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "temperature": kwargs.get("temperature", self.temperature),
                "top_p": kwargs.get("top_p", self.top_p),
                "top_k": kwargs.get("top_k", self.top_k),
                "frequency_penalty": kwargs.get("frequency_penalty", self.frequency_penalty),
            }

            for key, value in optional_params.items():
                if value is not None:
                    request_params[key] = value

            conn = trace.current_conn()
            self._maybe_include_stream_usage(request_params, conn)
            t_start = time.monotonic()
            trace.mark(conn, "llm_start")
            self._trace_request(conn, session_id, request_params, "response_with_functions")
            stream = self._create_with_retry(**request_params)

            if self.aimi_device_gateway:
                dumped = trace.dump_obj(stream)
                usage, usage_missing = self._usage_from_chunk(stream)
                self.last_usage = usage
                trace.emit(
                    "llm.response",
                    conn,
                    {
                        **self._endpoint_meta(),
                        "kind": "non_stream_tools",
                        "chunk": dumped,
                        "usage": usage,
                        "usage_missing": usage_missing,
                        "elapsed_ms": round((time.monotonic() - t_start) * 1000.0, 3),
                    },
                )
                message = stream.choices[0].message if stream.choices else None
                yield (getattr(message, "content", "") or ""), getattr(message, "tool_calls", None)
                return

            first = True
            usage_seen = False
            cached_tokens = None
            last_finish = None
            upstream_id = None
            for chunk in stream:
                dumped = trace.dump_obj(chunk)
                if isinstance(dumped, dict) and dumped.get("id") and not upstream_id:
                    upstream_id = dumped.get("id")
                usage, usage_missing = self._usage_from_chunk(chunk)
                if usage is not None:
                    usage_seen = True
                    self.last_usage = usage
                    ct = self._cached_tokens(usage)
                    if ct is not None:
                        cached_tokens = ct
                finish_reason = None
                if getattr(chunk, "choices", None):
                    delta = chunk.choices[0].delta
                    content = getattr(delta, "content", "")
                    tool_calls = getattr(delta, "tool_calls", None)
                    finish_reason = getattr(chunk.choices[0], "finish_reason", None)
                    if finish_reason:
                        last_finish = finish_reason
                    if content and first:
                        first = False
                        trace.mark(conn, "llm_first_token")
                    trace.emit(
                        "llm.chunk",
                        conn,
                        {
                            **self._endpoint_meta(),
                            "chunk": dumped,
                            "usage": usage,
                            "usage_missing": usage_missing,
                            "finish_reason": finish_reason,
                            "has_tool_calls": tool_calls is not None,
                        },
                    )
                    yield content, tool_calls
                elif isinstance(getattr(chunk, "usage", None), CompletionUsage):
                    usage_info = getattr(chunk, "usage", None)
                    usage_seen = True
                    self.last_usage = trace.dump_obj(usage_info)
                    cached_tokens = self._cached_tokens(self.last_usage)
                    trace.emit(
                        "llm.chunk",
                        conn,
                        {
                            **self._endpoint_meta(),
                            "chunk": dumped,
                            "usage": trace.dump_obj(usage_info),
                            "usage_missing": False,
                        },
                    )
                    try:
                        logger.bind(tag=TAG).info(
                            "Token 消耗：输入 {}，输出 {}，共计 {}".format(
                                getattr(usage_info, 'prompt_tokens', '未知'),
                                getattr(usage_info, 'completion_tokens', '未知'),
                                getattr(usage_info, 'total_tokens', '未知'),
                            )
                        )
                    except Exception:
                        pass  # logger 编码问题不影响主流程

            trace.emit(
                "llm.done",
                conn,
                {
                    **self._endpoint_meta(),
                    "first_token_ms": trace.latency_ms(conn, "llm_start", "llm_first_token"),
                    "elapsed_ms": round((time.monotonic() - t_start) * 1000.0, 3),
                    "usage_missing": not usage_seen,
                    "prompt_tokens": (self.last_usage or {}).get("prompt_tokens", "unknown"),
                    "completion_tokens": (self.last_usage or {}).get("completion_tokens", "unknown"),
                    "cached_tokens": cached_tokens if cached_tokens is not None else "unknown",
                    "finish_reason": last_finish,
                    "upstream_request_id": upstream_id,
                },
            )

        except Exception as e:
            from core.utils.context_window import ContextLimitError, is_context_limit
            self._usage_local.error = {"type":type(e).__name__,"status":getattr(e,"status_code",None),"code":getattr(e,"code",None)}
            if is_context_limit(e):
                raise ContextLimitError("upstream_context_limit") from e
            self._detect_stream_usage_unsupported(e)
            err_str = str(e).encode("utf-8", errors="replace").decode("utf-8")
            host = ""
            try:
                from urllib.parse import urlparse

                host = urlparse(self.base_url or "").netloc or ""
            except Exception:
                host = ""
            logger.bind(tag=TAG).error(
                f"Error in function call streaming: provider={self.provider_config_name} "
                f"type={self.provider_type} model={self.model_name} host={host} "
                f"config_key=LLM.{self.provider_config_name}.api_key err={err_str}"
            )
            trace.emit(
                "llm.error",
                trace.current_conn(),
                {**self._endpoint_meta(), "error_type": type(e).__name__, "error": err_str},
            )
            yield "【服务暂时无法响应，请稍后再试】", None

