"""Immutable stream ownership across producer threads, asyncio callbacks and queues."""
import contextvars
import functools
import queue
import time
import uuid

stream_context = contextvars.ContextVar('tts_stream_owner', default=None)


def current_stream(conn):
    return (getattr(conn,'session_id',None), getattr(conn,'sentence_id',None),
            getattr(conn,'tts_abort_epoch',0))


def stream_valid(conn, owner):
    return owner is None or owner == current_stream(conn)


def owned_send(fn):
    @functools.wraps(fn)
    async def wrapped(conn, *args, **kwargs):
        owner = kwargs.pop('stream_token', None) or stream_context.get() or current_stream(conn)
        if not stream_valid(conn,owner):
            return
        token = stream_context.set(owner)
        try:
            return await fn(conn,*args,**kwargs)
        finally:
            stream_context.reset(token)
    return wrapped


class AudioItem(tuple):
    def __new__(cls, values, owner):
        item = super().__new__(cls,values)
        item.stream_token = owner
        return item


class StreamAudioQueue(queue.Queue):
    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def put(self, item, block=True, timeout=None):
        owner = getattr(item,'stream_token',None) or stream_context.get() or current_stream(self.provider.conn)
        if stream_valid(self.provider.conn, owner):
            super().put(AudioItem(item,owner), block=block, timeout=timeout)


class StreamTextQueue(queue.Queue):
    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def put(self, item, block=True, timeout=None):
        conn = self.provider.conn
        if conn is not None and not getattr(conn,'sentence_id',None) and not getattr(item,'sentence_id',None):
            conn.sentence_id = uuid.uuid4().hex
            item.sentence_id = conn.sentence_id
        if not hasattr(item,'stream_token'):
            sid, sentence, epoch = current_stream(conn)
            dto_epoch = getattr(item, 'abort_epoch', None)
            if dto_epoch is not None:
                try:
                    epoch = int(dto_epoch)
                except (TypeError, ValueError):
                    pass
            item.stream_token = (sid, getattr(item,'sentence_id',None) or sentence, epoch)
        super().put(item,block=block,timeout=timeout)

    def get(self, block=True, timeout=None):
        deadline = time.monotonic()+timeout if timeout is not None else None
        while True:
            remaining = max(0,deadline-time.monotonic()) if deadline is not None else None
            item = super().get(block=block,timeout=remaining)
            if stream_valid(self.provider.conn,item.stream_token):
                stream_context.set(item.stream_token)
                return item
