"""Bounded connection-scoped output provenance, for echo authorization checks."""
import re,time
from collections import deque


def key(text):
    from core.utils.operation_control import content_text
    return re.sub(r'[^\w\u4e00-\u9fff]','',content_text(str(text))).lower()


def note_device_speech(conn,text,source='server_tts',request_id=None,now=None):
    if not key(text):return
    rows=getattr(conn,'_device_speech_sources',None)
    if not isinstance(rows,deque):rows=deque(maxlen=32);conn._device_speech_sources=rows
    rows.append({'text':key(text),'source':source,'at':time.monotonic() if now is None else now,'request_id':request_id,'session':getattr(conn,'session_id',None)})


def matches_device_speech(conn,text,now=None):
    current=time.monotonic() if now is None else now
    value=key(text)
    if not value:return False
    return any(row['session']==getattr(conn,'session_id',None) and 0<=current-row['at']<=20 and value==row['text'] for row in getattr(conn,'_device_speech_sources',()))
