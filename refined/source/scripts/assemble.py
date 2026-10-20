"""Assemble exported pages into long-page previews.

    python3 source/scripts/assemble.py

Writes to exports/long-page/:
  xiaonian-long-page-part-N.png   full-resolution parts (split at page boundaries, <= ~9000 px tall)
  xiaonian-long-page-full.jpg     lightweight preview of the whole page (720 px wide)
  contact-sheet.jpg               all pages side by side for a pacing overview
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "exports" / "pages"
OUT = ROOT / "exports" / "long-page"
MAX_PART = 9000


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    files = sorted(PAGES.glob("*.png"))
    images = [Image.open(f).convert("RGB") for f in files]

    parts, cur = [], []
    for im in images:
        if cur and sum(i.height for i in cur) + im.height > MAX_PART:
            parts.append(cur)
            cur = []
        cur.append(im)
    parts.append(cur)

    for n, group in enumerate(parts, 1):
        canvas = Image.new("RGB", (1440, sum(i.height for i in group)))
        y = 0
        for im in group:
            canvas.paste(im, (0, y))
            y += im.height
        canvas.save(OUT / f"xiaonian-long-page-part-{n}.png", optimize=True)
        print(f"part {n}: {len(group)} pages, {canvas.height}px")

    total = sum(i.height for i in images)
    scale = 720 / 1440
    full = Image.new("RGB", (720, round(total * scale)))
    y = 0
    for im in images:
        small = im.resize((720, round(im.height * scale)), Image.LANCZOS)
        full.paste(small, (0, y))
        y += small.height
    full.save(OUT / "xiaonian-long-page-full.jpg", quality=82, optimize=True, progressive=True)
    print(f"full preview: 720x{full.height}")

    th = 900
    thumbs = [im.resize((round(im.width * th / im.height), th), Image.LANCZOS) for im in images]
    sheet = Image.new("RGB", (sum(t.width for t in thumbs) + 20 * (len(thumbs) + 1), th + 40), (200, 200, 200))
    x = 20
    for t in thumbs:
        sheet.paste(t, (x, 20))
        x += t.width + 20
    sheet.save(OUT / "contact-sheet.jpg", quality=85)


if __name__ == "__main__":
    main()
