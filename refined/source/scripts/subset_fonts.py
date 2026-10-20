"""Subset the Noto SC fonts to the characters used in source/pages/.

    python3 source/scripts/subset_fonts.py /path/to/full/fonts

The full TTFs (Noto Sans SC / Noto Serif SC, SIL OFL) can be fetched with
source/scripts/fetch_fonts.sh. Re-run this script after adding new copy so
every glyph is present; render.mjs reports any font that fails to load.
"""
import re
import sys
from pathlib import Path

from fontTools import subset

SRC = Path(__file__).resolve().parents[1]
FULL = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC / "fonts" / "full"
OUT = SRC / "fonts"
FACES = ["NotoSansSC-400", "NotoSansSC-500", "NotoSansSC-700", "NotoSerifSC-500", "NotoSerifSC-600", "NotoSerifSC-700"]

text = "".join(p.read_text(encoding="utf-8") for p in (SRC / "pages").glob("*.html"))
text = re.sub(r"<[^>]+>", "", text)
# Printable ASCII plus common CJK punctuation is always kept so small copy edits keep working.
chars = set(text) | {chr(c) for c in range(0x20, 0x7F)} | set("，。、：；！？“”‘’（）《》【】—…·×¥～")
chars = "".join(sorted(c for c in chars if ord(c) >= 0x20))

for face in FACES:
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    font = subset.load_font(str(FULL / f"{face}.ttf"), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=chars)
    sub.subset(font)
    subset.save_font(font, str(OUT / f"{face}.woff2"), opts)
    print(face, (OUT / f"{face}.woff2").stat().st_size // 1024, "KB")
print(len(chars), "characters")
