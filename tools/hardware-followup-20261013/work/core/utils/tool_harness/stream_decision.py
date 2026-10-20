"""Incremental JSON envelope parser. Only the final reply string can be emitted."""
import json


class ReplyStream:
    def __init__(self, emit=None, admit=None):
        self.buffer = ''
        self.emit = emit
        self.admit = admit or (lambda meta: meta.get('mode') in {'chat', 'clarify'}
                              and not meta.get('steps') and not meta.get('authorized_writes'))
        self.decoder = json.JSONDecoder(object_pairs_hook=self.unique)
        self.pos = 0
        self.meta = {}
        self.phase = 'start'
        self.key = None
        self.reply_start = None
        self.decoded = ''
        self.emitted = 0

    @staticmethod
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = value
        return result

    def ws(self):
        while self.pos < len(self.buffer) and self.buffer[self.pos].isspace():
            self.pos += 1

    def feed(self, delta):
        self.buffer += delta
        while True:
            self.ws()
            if self.pos >= len(self.buffer):
                return
            if self.phase == 'start':
                if self.buffer[self.pos] != '{':
                    raise ValueError('decision_must_be_object')
                self.pos += 1
                self.phase = 'key'
            elif self.phase == 'key':
                if self.buffer[self.pos] == '}':
                    self.pos += 1
                    self.phase = 'done'
                    continue
                try:
                    key, end = self.decoder.raw_decode(self.buffer, self.pos)
                except json.JSONDecodeError:
                    return
                if not isinstance(key, str) or key in self.meta:
                    raise ValueError('invalid_or_duplicate_key')
                self.key, self.pos, self.phase = key, end, 'colon'
            elif self.phase == 'colon':
                if self.buffer[self.pos] != ':':
                    raise ValueError('missing_json_colon')
                self.pos += 1
                self.phase = 'value'
            elif self.phase == 'value':
                if self.key == 'reply':
                    if self.buffer[self.pos] != '"':
                        raise ValueError('reply_must_be_string')
                    self.reply_start = self.pos
                    self.phase = 'reply'
                else:
                    try:
                        value, end = self.decoder.raw_decode(self.buffer, self.pos)
                    except json.JSONDecodeError:
                        return
                    # A number/keyword may not be complete at the chunk boundary.
                    if end == len(self.buffer):
                        return
                    self.meta[self.key], self.pos, self.phase = value, end, 'separator'
            elif self.phase == 'separator':
                char = self.buffer[self.pos]
                if char == ',':
                    self.pos += 1
                    self.phase = 'key'
                elif char == '}':
                    self.pos += 1
                    self.phase = 'done'
                else:
                    raise ValueError('invalid_json_separator')
            elif self.phase == 'reply':
                # Decode complete JSON string atoms, including escaped surrogate pairs.
                i = self.reply_start + 1
                chars = []
                closed = False
                while i < len(self.buffer):
                    char = self.buffer[i]
                    if char == '"':
                        closed = True
                        break
                    if char == '\\':
                        if i + 1 >= len(self.buffer):
                            break
                        width = 6 if self.buffer[i + 1] == 'u' else 2
                        if i + width > len(self.buffer):
                            break
                        atom = self.buffer[i:i + width]
                        if width == 6:
                            try:
                                code = int(atom[2:], 16)
                            except ValueError:
                                raise ValueError('invalid_unicode_escape')
                            if 0xD800 <= code <= 0xDBFF:
                                if i + 12 > len(self.buffer):
                                    break
                                atom = self.buffer[i:i + 12]
                                width = 12
                        chars.append(json.loads('"' + atom + '"'))
                        i += width
                    else:
                        if ord(char) < 32:
                            raise ValueError('unescaped_control_character')
                        chars.append(char)
                        i += 1
                self.decoded = ''.join(chars)
                if self.emit and self.admit(dict(self.meta)):
                    self.emit(self.decoded)
                if not closed:
                    return
                self.meta['reply'] = self.decoded
                self.pos, self.phase = i + 1, 'reply_end'
            elif self.phase == 'reply_end':
                if self.buffer[self.pos] != '}':
                    # Reply must be last: future fields cannot authorize an operation.
                    raise ValueError('reply_must_be_last')
                self.pos += 1
                self.phase = 'done'
            elif self.phase == 'done':
                raise ValueError('trailing_json_content')

    def finish(self):
        result = self.decoder.decode(self.buffer)
        if self.phase != 'done' or not isinstance(result, dict):
            raise ValueError('incomplete_decision')
        return result
