"""Offline Qwen -> production queues/sender -> loopback WebSocket/Opus tests.

Only synthesis is faked. No LLM, paid TTS, physical device, or public listener.
The software receiver enforces start/closed-generation admission, but is not
an ESP32 emulator; firmware task scheduling and I2S are tested separately.
"""
from __future__ import annotations

import asyncio
import json
import math
import struct
import sys
import threading
import unittest
import uuid
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config.settings
config.settings.config_file_valid = True

from aiohttp import ClientSession, WSMsgType, web
from opuslib_next import Decoder
from test_qwen_audio_tts_plus import FakeConn, FakeWS
from core.handle.abortHandle import handleAbortMessage
from core.handle.sendAudioHandle import sendAudioMessage
from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO
from core.providers.tts.qwen_audio_tts_plus import TTSProvider
from core.utils.device_outbound import begin_tts_turn, enqueue_tts
from core.utils.opus_encoder_utils import OpusEncoderUtils
from core.utils.tts_stream import current_stream


PCM_FRAME = array('h', [int(6000 * math.sin(2 * math.pi * 440 * i / 16000))
                        for i in range(960)]).tobytes()


class PcmUpstream(FakeWS):
    def __init__(self, frames):
        super().__init__()
        self.frames = frames
        self.texts = []

    async def send(self, data):
        await super().send(data)
        message = json.loads(data)
        header = message['header']
        action = header['action']
        task_id = header['task_id']
        if action == 'run-task':
            await self.incoming.put(json.dumps({'header': {
                'event': 'task-started', 'task_id': task_id}}))
        elif action == 'continue-task':
            self.texts.append(message['payload']['input']['text'])
        elif action == 'finish-task':
            if not message.get('payload', {}).get('input', {}).get('cancel'):
                await self.incoming.put(json.dumps({'header': {
                    'event': 'result-generated', 'task_id': task_id}}))
                await self.incoming.put(PCM_FRAME * self.frames)
            await self.incoming.put(json.dumps({'header': {
                'event': 'task-finished', 'task_id': task_id}}))


class DeviceStartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = FakeConn(asyncio.get_running_loop(),
                             session_id='offline-start-test',
                             device_id='SOFTWARE-DEVICE-ONLY')
        self.conn.stop_event = threading.Event()
        self.conn.config = {'enable_stop_tts_notify': False,
                            'tts_audio_send_delay': -1}
        self.conn.conn_from_mqtt_gateway = False
        self.conn.audio_protocol_version = 2
        self.conn.close_after_chat = False
        self.conn.read_config_from_api = False
        self.conn.max_output_size = 0
        self.conn.headers = {}
        self.conn._cid = lambda: 'offline-start-test'
        self.sockets = []
        self.frames_per_unit = 4
        self.provider = None
        self.events = []
        self.subtitles = []
        self.errors = []
        self.cycles = asyncio.Queue()
        self.first_audio = asyncio.Event()
        self.uplink_ready = asyncio.Event()
        self.uplink_count = 0
        self.uplink_during_reply = 0
        self.active = False
        self.generation = 0
        self.closed_generation = 0
        self.rx_frames = 0
        self.accepted_frames = 0
        self.dropped_frames = 0
        self.pcm_bytes = 0
        self.decoder = Decoder(16000, 1)
        self.tasks = []
        self.server_ws = None

        async def endpoint(request):
            self.server_ws = web.WebSocketResponse()
            await self.server_ws.prepare(request)
            async for message in self.server_ws:
                if message.type == WSMsgType.BINARY:
                    self._payload(message.data)
                    self.uplink_count += 1
                    self.uplink_during_reply += int(self.active)
                    self.uplink_ready.set()
            return self.server_ws

        app = web.Application()
        app.router.add_get('/device', endpoint)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.http = ClientSession()
        self.device_ws = await self.http.ws_connect(
            f'http://127.0.0.1:{port}/device', autoping=True)

        async def send(device_id, data, **kwargs):
            if not self.conn.server.is_current_connection(device_id, self.conn):
                return False
            if isinstance(data, bytes):
                await self.server_ws.send_bytes(data)
            else:
                await self.server_ws.send_str(data)
            return True

        self.conn.server.send_to_current = send
        self.conn.server.is_current_connection = lambda d, c: (
            c is self.conn and d == c.device_id and not c.superseded)
        self.tasks.append(asyncio.create_task(self._receive()))
        encoded = []
        OpusEncoderUtils(16000, 1, 60).encode_pcm_to_opus_stream(
            PCM_FRAME, False, encoded.append)
        self.uplink_payload = encoded[0]
        self.tasks.append(asyncio.create_task(self._upload()))
        await asyncio.wait_for(self.uplink_ready.wait(), 2)

    def _payload(self, data):
        self.assertGreaterEqual(len(data), 16)
        version, kind, reserved, timestamp, size = struct.unpack('!HHIII', data[:16])
        self.assertEqual((version, kind, reserved), (2, 0, 0))
        self.assertEqual(size, len(data) - 16)
        return data[16:]

    async def _upload(self):
        while not self.device_ws.closed:
            payload = self.uplink_payload
            packet = struct.pack('!HHIII', 2, 0, 0, self.uplink_count * 60,
                                 len(payload)) + payload
            await self.device_ws.send_bytes(packet)
            await asyncio.sleep(.06)

    async def _receive(self):
        async for message in self.device_ws:
            if message.type == WSMsgType.TEXT:
                body = json.loads(message.data)
                state = body.get('state')
                if body.get('type') != 'tts':
                    continue
                self.events.append(state)
                if state == 'sentence_start':
                    self.subtitles.append({'text': body.get('text'),
                                           'audio_before': self.rx_frames,
                                           'generation': self.generation})
                if state == 'start':
                    if self.active:
                        self.errors.append('duplicate start within reply')
                    self.generation += 1
                    self.active = True
                    self.decoder.reset_state()
                elif state == 'stop':
                    self.active = False
                    self.closed_generation = self.generation
                    await self.cycles.put(len(self.events))
            elif message.type == WSMsgType.BINARY:
                self.events.append('audio')
                self.rx_frames += 1
                payload = self._payload(message.data)
                if not self.active or self.generation == self.closed_generation:
                    self.dropped_frames += 1
                    continue
                pcm = self.decoder.decode(payload, 960)
                self.assertEqual(len(pcm), 1920)
                self.pcm_bytes += len(pcm)
                self.accepted_frames += 1
                self.first_audio.set()

    async def _start_provider(self, official=True):
        async def connect(url, headers):
            socket = PcmUpstream(self.frames_per_unit)
            self.sockets.append(socket)
            return socket

        self.provider = TTSProvider({
            'api_key': 'sk-offline-test', 'voice': 'longanlingxi',
            'model': 'qwen-audio-3.0-tts-plus', 'sample_rate': 16000,
            'ws_url': 'ws://127.0.0.1:1/not-used',
            'official_enhanced': official,
            'official_model_id': 'TTS_QwenAudioTTSPlus', '_connect': connect,
        }, True)
        await self.provider.open_audio_channels(self.conn)
        self.conn.tts = self.provider

    def _enqueue(self, sentence_type, text=None):
        self.assertTrue(enqueue_tts(self.conn, TTSMessageDTO(
            sentence_id=self.conn.sentence_id, sentence_type=sentence_type,
            content_type=ContentType.TEXT, content_detail=text,
            session_id=self.conn.session_id, abort_epoch=self.conn.tts_abort_epoch)))

    def _begin(self, parts, finish=True):
        self.conn.sentence_id = uuid.uuid4().hex
        self.conn.tts_MessageText = ''.join(parts)
        begin_tts_turn(self.conn, self.conn.sentence_id)
        self._enqueue(SentenceType.FIRST)
        for text in parts:
            self._enqueue(SentenceType.MIDDLE, text)
        if finish:
            self._enqueue(SentenceType.LAST)

    async def _reply(self, parts, frames, captions=None):
        before = len(self.events)
        subtitle_before = len(self.subtitles)
        rx_before, accepted_before = self.rx_frames, self.accepted_frames
        self._begin(parts)
        await asyncio.wait_for(self.cycles.get(), 12)
        events = self.events[before:]
        self.assertEqual(events.count('start'), 1, events)
        self.assertEqual(events.count('stop'), 1, events)
        self.assertEqual(events[0], 'start', events)
        self.assertEqual(events[-1], 'stop', events)
        self.assertLess(events.index('sentence_start'), events.index('audio'))
        self.assertEqual(self.rx_frames - rx_before, frames)
        self.assertEqual(self.accepted_frames - accepted_before, frames)
        self.assertEqual(self.dropped_frames, 0)
        self.assertEqual(self.errors, [])
        self.assertFalse(self.device_ws.closed)
        received = self.subtitles[subtitle_before:]
        self.assertEqual([row['text'] for row in received],
                         parts if captions is None else captions)
        self.assertTrue(all(row['generation'] == self.generation for row in received))

    async def test_official_consecutive_three_replies(self):
        await self._start_provider()
        for text in ['Hello.', 'What time is it.', 'Another reply.']:
            await self._reply([text], 4)

    async def test_legacy_consecutive_two_replies(self):
        await self._start_provider(official=False)
        for text in ['First reply.', 'Second reply.']:
            await self._reply([text], 4)

    async def test_same_turn_two_sessions_92_frames_with_continuous_upload(self):
        await self._start_provider()
        await self._reply(['Greeting.'], 4)
        self.frames_per_unit = 46
        before = len(self.sockets)
        await self._reply(['The time is midnight\u3002', 'Still awake\u3002'], 92)
        self.assertEqual(len(self.sockets) - before, 2)
        self.assertTrue(self.sockets[-2].closed)
        self.assertGreater(self.uplink_during_reply, 50)
        self.assertEqual(self.pcm_bytes, 96 * 1920)
        self.assertEqual([row['audio_before'] for row in self.subtitles[-2:]], [4, 50])

    async def test_every_unit_caption_precedes_audio_including_final_flush(self):
        await self._start_provider()
        captions = ['\u597d\u597d\u597d\uff0c\u6211\u8fd9\u4e0d\u662f\u6015\u4f60\u5acc\u70e6\u561b\u3002',
                    '\u90a3\u4f60\u60f3\u804a\u70b9\u4ec0\u4e48\uff1f',
                    '\u6211\u966a\u7740\u4f60']
        await self._reply(captions, 12)
        self.assertEqual([row['audio_before'] for row in self.subtitles], [0, 4, 8])
        self.assertEqual(self.events, ['start'] +
                         (['sentence_start'] + ['audio'] * 4) * 3 + ['stop'])

    async def test_fragmented_text_emits_caption_once_per_compiled_unit(self):
        await self._start_provider()
        await self._reply(['\u7b2c\u4e00', '\u53e5\u3002', '\u7b2c\u4e8c', '\u53e5\uff1f'], 8,
                          captions=['\u7b2c\u4e00\u53e5\u3002', '\u7b2c\u4e8c\u53e5\uff1f'])
        self.assertEqual([row['audio_before'] for row in self.subtitles], [0, 4])

    async def test_abort_then_new_reply_rejects_old_audio(self):
        await self._start_provider()
        self.frames_per_unit = 46
        self._begin(['Interrupt this reply\u3002'], finish=False)
        old_owner = current_stream(self.conn)
        await asyncio.wait_for(self.first_audio.wait(), 3)
        await handleAbortMessage(self.conn)
        await asyncio.wait_for(self.cycles.get(), 3)
        pending = list(getattr(self.conn, '_tts_cancel_tasks', ()))
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), 3)
        before = len(self.events)
        self.frames_per_unit = 4
        await self._reply(['Fresh reply.'], 4)
        after = len(self.events)
        await sendAudioMessage(self.conn, SentenceType.MIDDLE,
                               self.uplink_payload, None, stream_token=old_owner)
        self.assertEqual(len(self.events), after)
        self.assertGreater(after, before)

    async def test_stale_first_cannot_rearm_current_turn(self):
        await self._start_provider()
        self.provider.tts_audio_first_sentence = False
        self.conn.tts_abort_epoch = 1
        stale = TTSMessageDTO(self.conn.sentence_id, SentenceType.FIRST,
                              ContentType.TEXT, abort_epoch=0)
        self.provider._handle_official_message(stale)
        self.assertFalse(self.provider.tts_audio_first_sentence)
        self.provider._handle_legacy_message(stale)
        self.assertFalse(self.provider.tts_audio_first_sentence)

    async def asyncTearDown(self):
        self.conn.stop_event.set()
        if self.provider:
            await self.provider.close()
            threads = [self.provider.tts_priority_thread,
                       self.provider.audio_play_priority_thread]
            for thread in threads:
                await asyncio.to_thread(thread.join, 2)
                self.assertFalse(thread.is_alive(), 'TTS test worker leaked')
        for task in self.tasks:
            task.cancel()
        results = await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.device_ws.close()
        await self.http.close()
        await self.runner.cleanup()
        for result in results:
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                raise result
        print('TTS_DEVICE_EVIDENCE', json.dumps({
            'test': self.id().rsplit('.', 1)[-1],
            'downlink_frames': self.rx_frames,
            'accepted_frames': self.accepted_frames,
            'dropped_frames': self.dropped_frames,
            'decoded_pcm_bytes': self.pcm_bytes,
            'upstream_sessions': len(self.sockets),
            'uplink_frames': self.uplink_count,
            'uplink_during_reply': self.uplink_during_reply,
            'starts': self.events.count('start'),
            'stops': self.events.count('stop'),
            'subtitles': self.subtitles,
            'errors': self.errors,
            'physical_device': False, 'paid_model_calls': 0,
        }, sort_keys=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
