import re

EMOJI_RANGES = [
    (0x1F600, 0x1F64F),
    (0x1F300, 0x1F5FF),
    (0x1F680, 0x1F6FF),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
]


def get_string_no_punctuation_or_emoji(s):
    """去除字符串首尾的空格、标点符号和表情符号"""
    chars = list(s)
    # 处理开头的字符
    start = 0
    while start < len(chars) and is_punctuation_or_emoji(chars[start]):
        start += 1
    # 处理结尾的字符
    end = len(chars) - 1
    while end >= start and is_punctuation_or_emoji(chars[end]):
        end -= 1
    return "".join(chars[start : end + 1])


def is_punctuation_or_emoji(char):
    """检查字符是否为空格、指定标点或表情符号"""
    # 定义需要去除的中英文标点（包括全角/半角）
    punctuation_set = {
        "，",
        ",",  # 中文逗号 + 英文逗号
        "。",
        ".",  # 中文句号 + 英文句号
        "！",
        "!",  # 中文感叹号 + 英文感叹号
        "“",
        "”",
        '"',  # 中文双引号 + 英文引号
        "：",
        ":",  # 中文冒号 + 英文冒号
        "-",
        "－",  # 英文连字符 + 中文全角横线
        "、",  # 中文顿号
        "[",
        "]",  # 方括号
        "【",
        "】",  # 中文方括号
    }
    if char.isspace() or char in punctuation_set:
        return True
    return is_emoji(char)


def is_emoji(char):
    """检查字符是否为emoji表情"""
    code_point = ord(char)
    return any(start <= code_point <= end for start, end in EMOJI_RANGES)


_DISPLAY_EMOJI_PATTERN = re.compile(
    r"[0-9#*]\ufe0f?\u20e3"
    r"|[\U0001F000-\U0001FAFF\u2600-\u27BF]"
    r"|[\u00a9\u00ae\u203c\u2049\u2122\u2139\u2194-\u2199"
    r"\u21a9\u21aa\u231a\u231b\u2328\u23cf\u23e9-\u23f3"
    r"\u23f8-\u23fa\u24c2\u25aa\u25ab\u25b6\u25c0\u25fb-\u25fe"
    r"\u2934\u2935\u2b05-\u2b07\u2b1b\u2b1c\u2b50\u2b55\u3030\u303d\u3297\u3299]"
    r"|[\u200d\ufe0e\ufe0f\u20e3\U000E0020-\U000E007F]"
)


def strip_display_emoji(text):
    """Remove display emoji and their sequence markers; retain speech tags and newlines."""
    if not text:
        return text
    return _DISPLAY_EMOJI_PATTERN.sub('', text)


def check_emoji(text):
    """去除文本中的所有emoji表情"""
    return strip_display_emoji(text).replace("\n", "")


# 残留 [emotion:xxx] 清洗：prompt 已不再生成，TTS 仍剥掉以免被念出
EMOTION_TAG_GLOBAL_PATTERN = re.compile(r'\[emotion\s*:\s*\w+\s*\]', re.IGNORECASE)


def strip_all_emotion_tags(text):
    """移除文本中所有 [emotion:xxx] 标签，避免 TTS 朗读。"""
    if not text:
        return text
    return EMOTION_TAG_GLOBAL_PATTERN.sub('', text)
