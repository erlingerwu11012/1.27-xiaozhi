import json
import time
import uuid
import hmac
import base64
import hashlib
import asyncio
import requests
import websockets
import opuslib_next
import random
from typing import Optional, Tuple, List
from dataclasses import dataclass, field
from collections import deque
from core.utils.audio_ingress import audio_count, log_audio_stats
from urllib import parse
from datetime import datetime
from config.logger import setup_logging
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType
from core.utils.device_outbound import guarded_ws_send

TAG = __name__
logger = setup_logging()


class AccessToken:
    @staticmethod
    def _encode_text(text):
        encoded_text = parse.quote_plus(text)
        return encoded_text.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")

    @staticmethod
    def _encode_dict(dic):
        keys = dic.keys()
        dic_sorted = [(key, dic[key]) for key in sorted(keys)]
        encoded_text = parse.urlencode(dic_sorted)
        return encoded_text.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")

    @staticmethod
    def create_token(access_key_id, access_key_secret):
        parameters = {
            "AccessKeyId": access_key_id,
            "Action": "CreateToken",
            "Format": "JSON",
            "RegionId": "cn-shanghai",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid1()),
            "SignatureVersion": "1.0",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version": "2019-02-28",
        }
        query_string = AccessToken._encode_dict(parameters)
        string_to_sign = (
            "GET" + "&" + AccessToken._encode_text("/") + "&" + AccessToken._encode_text(query_string)
        )
        secreted_string = hmac.new(
            bytes(access_key_secret + "&", encoding="utf-8"),
            bytes(string_to_sign, encoding="utf-8"),
            hashlib.sha1,
        ).digest()
        signature = base64.b64encode(secreted_string)
        signature = AccessToken._encode_text(signature)
        full_url = "https://nls-meta.cn-shanghai.aliyuncs.com/?Signature=%s&%s" % (signature, query_string)
        response = requests.get(full_url, timeout=(3, 5))
        if response.ok:
            root_obj = response.json()
            if "Token" in root_obj:
                return root_obj["Token"]["Id"], root_obj["Token"]["ExpireTime"]
        return None, None


@dataclass
class Recognition:
    epoch: int
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = 'STARTING'
    ws: object = None
    reader: object = None
    decoder: object = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: deque = field(default_factory=deque)
    audio: deque = field(default_factory=lambda: deque(maxlen=600))
    started: float = field(default_factory=time.monotonic)
    last_pcm: float = field(default_factory=time.monotonic)
    stopping_at: float = 0.0
    text: str = ''
    delivered: bool = False
    stop_sent: bool = False
    closed: bool = False


class ASRProvider(ASRProviderBase):
    def __init__(self, config, delete_audio_file):
        super().__init__()
        self.interface_type = InterfaceType.STREAM
        self.config = config
        self.text = ""
        self.decoder = opuslib_next.Decoder(16000, 1)
        self.asr_ws = None
        self.forward_task = None
        self.is_processing = False
        self.server_ready = False
        self._current = None
        self._start_lock = asyncio.Lock()
        self._deliveries = set()
        self._closed = False
        self.ready_timeout = float(config.get('ready_timeout', 5))
        self.stop_timeout = float(config.get('stop_timeout', 2))
        self.idle_timeout = min(float(config.get('idle_timeout', 8)), 9)

        # 基础配置
        self.access_key_id = config.get("access_key_id")
        self.access_key_secret = config.get("access_key_secret")
        self.appkey = config.get("appkey")
        self.token = config.get("token")
        self.host = config.get("host", "nls-gateway-cn-shanghai.aliyuncs.com")
        # 如果配置的是内网地址（包含-internal.aliyuncs.com），则使用ws协议，默认是wss协议
        if "-internal." in self.host:
            self.ws_url = f"ws://{self.host}/ws/v1"
        else:
            # 默认使用wss协议
            self.ws_url = f"wss://{self.host}/ws/v1"

        self.max_sentence_silence = config.get("max_sentence_silence")
        # 最大强制断句时长（秒），超时未自然断句时强行截断，默认 15 秒
        self.max_forced_segmentation_duration = config.get("max_forced_segmentation_duration", 15)
        self.output_dir = config.get("output_dir", "./audio_output")
        self.delete_audio_file = delete_audio_file
        self.expire_time = None

        self.task_id = uuid.uuid4().hex

        # Token管理
        if not self.token and not (self.access_key_id and self.access_key_secret):
            raise ValueError("必须提供access_key_id+access_key_secret或者直接提供token")

    def _refresh_token(self):
        """刷新Token"""
        self.token, expire_time_str = AccessToken.create_token(self.access_key_id, self.access_key_secret)
        if not self.token:
            raise ValueError("无法获取有效的访问Token")
        
        try:
            expire_str = str(expire_time_str).strip()
            if expire_str.isdigit():
                expire_time = datetime.fromtimestamp(int(expire_str))
            else:
                expire_time = datetime.strptime(expire_str, "%Y-%m-%dT%H:%M:%SZ")
            self.expire_time = expire_time.timestamp() - 60
        except:
            self.expire_time = None

    def _is_token_expired(self):
        """检查Token是否过期"""
        return self.expire_time and time.time() > self.expire_time

    async def _send_listen_stop_to_client(self, conn, text: str = None):
        """立即向客户端下发停止录音指令，告知其可以闭麦（云端接管断句模式）"""
        from core.utils.reminder_interaction import is_interaction_active

        if is_interaction_active(conn):
            logger.bind(tag=TAG).debug(
                "reminder interaction active, skip listen/stop"
            )
            return
        try:
            if text:
                msg = {"type": "listen", "state": "stop", "text": text}
            else:
                msg = {"type": "listen", "state": "stop"}
            await guarded_ws_send(
                conn, json.dumps(msg, ensure_ascii=False), command="listen", msg_type="listen"
            )
            logger.bind(tag=TAG).debug(f"已下发 listen/stop 指令，通知客户端闭麦")
        except Exception as e:
            logger.bind(tag=TAG).warning(f"下发 listen/stop 指令失败: {e}")

    async def open_audio_channels(self, conn):
        await super().open_audio_channels(conn)

    def _valid(self, conn, ctx):
        return not self._closed and self._current is ctx and ctx.epoch == getattr(conn, 'listen_epoch', 0) and not conn.stop_event.is_set()

    async def start_listening(self, conn, reason="new_listen"):
        await self.stop_listening(conn, reason=reason)
        conn.asr_audio.clear()
        conn.asr_audio_for_voiceprint = []

    async def stop_listening(self, conn, reason="device_stop"):
        ctx = self._current
        if ctx:
            await self._cleanup(conn, ctx)

    async def receive_audio(self, conn, audio, audio_have_voice):
        if self._closed or not audio:
            return
        epoch = getattr(conn, 'listen_epoch', 0)
        ctx = self._current
        if ctx and ctx.epoch != epoch:
            await self._cleanup(conn, ctx)
            ctx = None
        if ctx is None:
            conn.asr_audio.append(audio)
            conn.asr_audio = conn.asr_audio[-10:]
            have_voice = audio_have_voice or (conn.client_listen_mode == 'manual' and conn.client_have_voice)
            if not have_voice:
                return
            try:
                await self._start_recognition(conn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                audio_count(conn, 'start_failed')
                logger.bind(tag=TAG).warning(f'[ASR start_failed] epoch={epoch} type={type(exc).__name__}')
                await self._cleanup(conn)
            return
        if ctx.state not in ('STARTING','RUNNING') or not self._valid(conn, ctx):
            audio_count(conn, 'drop_stopping')
            return
        ctx.audio.append(audio)
        if len(ctx.pending) >= 50:
            ctx.pending.popleft()
            audio_count(conn, 'drop_ready_buffer_full')
        ctx.pending.append(audio)
        if ctx.state == 'RUNNING':
            await self._flush_audio(conn, ctx)

    async def _start_recognition(self, conn):
        async with self._start_lock:
            if self._closed or self._current:
                return
            ctx = Recognition(epoch=getattr(conn, 'listen_epoch', 0))
            ctx.decoder = opuslib_next.Decoder(16000, 1)
            ctx.pending.extend(conn.asr_audio[-10:])
            ctx.audio.extend(ctx.pending)
            conn.asr_audio.clear()
            self._current = ctx
            self.is_processing = True
            try:
                if not self.token or self._is_token_expired():
                    await asyncio.wait_for(asyncio.to_thread(self._refresh_token), timeout=9)
                ctx.ws = await asyncio.wait_for(websockets.connect(
                    self.ws_url, additional_headers={'X-NLS-Token': self.token},
                    max_size=1024*1024, ping_interval=None, ping_timeout=None,
                    close_timeout=2, open_timeout=5), timeout=6)
                if not self._valid(conn, ctx):
                    await asyncio.wait_for(ctx.ws.close(), timeout=2)
                    await self._finalize(conn, ctx)
                    return
                self.asr_ws, self.task_id = ctx.ws, ctx.task_id
                start = {'header':self._header(ctx, 'StartTranscription'), 'payload':{
                    'format':'pcm','sample_rate':16000,'enable_intermediate_result':True,
                    'enable_punctuation_prediction':True,'enable_inverse_text_normalization':True,
                    'enable_voice_detection':False}}
                if self.max_sentence_silence is not None:
                    start['payload']['max_sentence_silence'] = self.max_sentence_silence
                await asyncio.wait_for(ctx.ws.send(json.dumps(start)), timeout=3)
                ctx.reader = asyncio.create_task(self._forward_results(conn, ctx))
                self.forward_task = ctx.reader
                logger.bind(tag=TAG).info(f'[ASR task] epoch={ctx.epoch} task_id={ctx.task_id} state=STARTING')
            except BaseException:
                await self._finalize(conn, ctx)
                raise

    def _header(self, ctx, name):
        return {'namespace':'SpeechTranscriber','name':name,'message_id':uuid.uuid4().hex,
                'task_id':ctx.task_id,'appkey':self.appkey}

    async def _flush_audio(self, conn, ctx):
        async with ctx.send_lock:
            while ctx.pending and self._valid(conn, ctx) and ctx.state == 'RUNNING':
                audio = ctx.pending.popleft()
                try:
                    pcm = audio if conn.audio_format == 'pcm' else ctx.decoder.decode(audio,960)
                    audio_count(conn, 'decode_ok')
                except Exception:
                    audio_count(conn, 'decode_error')
                    continue
                try:
                    await asyncio.wait_for(ctx.ws.send(pcm),timeout=2)
                    ctx.last_pcm = time.monotonic()
                    audio_count(conn,'pcm_sent_frames')
                    audio_count(conn,'pcm_sent_bytes',len(pcm))
                except Exception:
                    audio_count(conn,'pcm_send_failed')
                    # The reader closes its own socket; do not wait for it while holding send_lock.
                    ctx.state = 'FAILED'
                    return

    async def _request_stop(self, conn, ctx, reason):
        async with ctx.send_lock:
            if ctx.closed or ctx.stop_sent or ctx.state != 'RUNNING':
                return
            ctx.stop_sent = True
            ctx.state = 'STOPPING'
            ctx.stopping_at = time.monotonic()
            try:
                await asyncio.wait_for(ctx.ws.send(json.dumps({'header':self._header(ctx,'StopTranscription')})), timeout=2)
            except Exception:
                ctx.state = 'FAILED'
            logger.bind(tag=TAG).info(f'[ASR stop] epoch={ctx.epoch} task_id={ctx.task_id} reason={reason}')

    def _deliver(self, conn, ctx):
        if ctx.delivered or not ctx.text or not self._valid(conn,ctx):
            return
        ctx.delivered = True
        text, audio = ctx.text, list(ctx.audio)
        async def dispatch():
            if ctx.epoch != getattr(conn,'listen_epoch',0) or conn.stop_event.is_set():
                return
            await self._send_listen_stop_to_client(conn,text)
            if ctx.epoch != getattr(conn,'listen_epoch',0):
                return
            conn.reset_vad_states()
            await self.handle_voice_stop(conn,audio,final_text=text,listen_epoch=ctx.epoch)
        task = asyncio.create_task(dispatch())
        self._deliveries.add(task)
        def finished(task):
            self._deliveries.discard(task)
            if not task.cancelled() and task.exception():
                logger.bind(tag=TAG).warning(f'ASR delivery failed: {type(task.exception()).__name__}')
        task.add_done_callback(finished)

    async def _forward_results(self, conn, ctx):
        try:
            while self._valid(conn,ctx) and ctx.state != 'FAILED':
                now = time.monotonic()
                if ctx.state == 'STARTING' and now-ctx.started > self.ready_timeout:
                    audio_count(conn,'ready_timeout')
                    break
                if ctx.state == 'RUNNING':
                    if now-ctx.last_pcm > self.idle_timeout:
                        await self._request_stop(conn,ctx,'audio_idle')
                    elif now-ctx.started > float(self.max_forced_segmentation_duration):
                        await self._request_stop(conn,ctx,'forced_segment')
                if ctx.state == 'STOPPING' and now-ctx.stopping_at > self.stop_timeout:
                    audio_count(conn,'completed_timeout')
                    break
                try:
                    raw = await asyncio.wait_for(ctx.ws.recv(),timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                result = json.loads(raw)
                header = result.get('header',{})
                if header.get('task_id') and header['task_id'] != ctx.task_id:
                    continue
                if header.get('status',20000000) != 20000000:
                    logger.bind(tag=TAG).warning(f'[ASR error] epoch={ctx.epoch} task_id={ctx.task_id} status={header.get("status")}')
                    break
                name = header.get('name')
                payload = result.get('payload',{})
                if name == 'TranscriptionStarted' and ctx.state == 'STARTING':
                    ctx.state = 'RUNNING'
                    ctx.started = ctx.last_pcm = time.monotonic()
                    self.server_ready = True
                    await self._flush_audio(conn,ctx)
                elif name in ('TranscriptionResultChanged','SentenceEnd'):
                    if isinstance(payload.get('result'), str) and payload['result']:
                        ctx.text = payload['result']
                    if name == 'SentenceEnd':
                        self._deliver(conn,ctx)
                        await self._request_stop(conn,ctx,'sentence_end')
                elif name == 'TranscriptionCompleted':
                    self._deliver(conn,ctx)
                    audio_count(conn,'completed')
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.bind(tag=TAG).warning(f'[ASR reader] epoch={ctx.epoch} type={type(exc).__name__}')
        finally:
            if ctx.stop_sent:
                self._deliver(conn,ctx)
            await self._finalize(conn,ctx)

    async def _finalize(self, conn, ctx):
        if ctx.closed:
            return
        ctx.closed = True
        ctx.state = 'CLOSED'
        try:
            if ctx.ws:
                await asyncio.wait_for(ctx.ws.close(),timeout=2)
        except Exception:
            pass
        finally:
            ctx.pending.clear()
            ctx.audio.clear()
            if self._current is ctx:
                self._current = None
                self.asr_ws = self.forward_task = None
                self.is_processing = self.server_ready = False
                if conn and ctx.epoch == getattr(conn,'listen_epoch',0):
                    conn.asr_audio_for_voiceprint = []
                    log_audio_stats(conn,'asr_closed')
            ctx.done.set()

    async def _cleanup(self, conn=None, ctx=None):
        ctx = ctx or self._current
        if not ctx or ctx.closed:
            return
        reader = ctx.reader
        try:
            if ctx.state == 'RUNNING':
                await self._request_stop(conn,ctx,'client_stop')
            if reader and reader is not asyncio.current_task() and not reader.done():
                try:
                    await asyncio.wait_for(ctx.done.wait(),timeout=self.stop_timeout+0.3)
                except asyncio.TimeoutError:
                    reader.cancel()
                    await asyncio.gather(reader,return_exceptions=True)
        finally:
            await self._finalize(conn,ctx)

    async def speech_to_text(self, opus_data, session_id, audio_format):
        # Streaming delivery passes immutable final_text to the base handler.
        return '', None

    async def close(self):
        self._closed = True
        await self._cleanup()
        pending = [t for t in self._deliveries if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending,return_exceptions=True)
