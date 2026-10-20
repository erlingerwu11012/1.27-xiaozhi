"""One request owns one incremental transcript, caption and TTS turn."""
import re,threading,time


class SpeechOutput:
    def __init__(self,valid,begin,send,end):
        self.valid,self.begin,self.send,self.end=valid,begin,send,end
        self.text=''
        self.started=False
        self.closed=False
        self.first_text_at=None
        self.lock=threading.RLock()

    def feed(self,text,check):
        with self.lock:
            if self.closed or not self.valid() or not text.startswith(self.text):return
            # Never pass an unfinished sentence to the voice pipeline.
            ends=[m.end() for m in re.finditer(r'[。！？!?；;](?:[”」\"])?',text)]
            end=max(ends,default=0)
            candidate=text[:end]
            if end<=len(self.text):return
            if not check(candidate):
                if self.text:self.fail('后面的内容还不能确认，先说到这里。')
                return
            self._send(candidate[len(self.text):])

    def _send(self,fragment):
        if not fragment:return
        if not self.started:
            self.begin();self.started=True;self.first_text_at=time.monotonic()
        self.send(fragment)
        self.text+=fragment

    def finish(self,text):
        with self.lock:
            if self.closed:return self.text
            if self.valid():
                # Already accepted speech cannot be replayed or rewritten.
                if text.startswith(self.text):self._send(text[len(self.text):])
                elif not self.text:self._send(text)
                if self.started:self.end()
            self.closed=True
            return self.text

    def abort(self):
        with self.lock:self.closed=True

    def fail(self,message='后续回复中断了。'):
        with self.lock:
            if self.closed:return
            if self.text and self.valid():
                self._send(message)
                if self.started:self.end()
                self.closed=True
