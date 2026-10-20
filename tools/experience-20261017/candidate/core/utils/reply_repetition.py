"""Remove adjacent verbatim sentence runs; no semantic rewrite or second model."""
import re
from core.providers.tts.official.compiler import caption_from


def remove_adjacent_repetition(text):
    parts = re.findall(r'[^。！？!?]+[。！？!?]*', text)
    keys = [re.sub(r'\s+', '', caption_from(re.sub(r'\[[a-z][a-z ]{1,30}\]', '', p, flags=re.I))) for p in parts]
    i = 0
    while i < len(parts):
        for n in range(min(12, (len(parts)-i)//2), 0, -1):
            if (sum(len(k) for k in keys[i:i+n]) >= 16
                    and keys[i:i+n] == keys[i+n:i+2*n]):
                del parts[i+n:i+2*n]
                del keys[i+n:i+2*n]
                break
        else:
            i += 1
    return ''.join(parts)
