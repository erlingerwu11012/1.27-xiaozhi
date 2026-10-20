# Xiaonian Crowdfunding Detail Page — Refined Edition

This is a revision of the owner-selected detail-page images from
`codex/crowdfunding-pages-claude-20261020`. Every section has been rebuilt as an
editable HTML/CSS layout and exported to 1440 px wide portrait PNGs. Section heights vary.
The Chinese marketing copy is kept as it was, with the exceptions listed in
`CHANGELOG.md`. Everything else in this handoff is in English.

## Output structure

```
exports/
  pages/                 15 full-resolution PNGs in reading order (1440 px wide)
  long-page/
    xiaonian-long-page-part-1..4.png   assembled page, split at section boundaries
    xiaonian-long-page-full.jpg        lightweight full-page preview (720 px wide)
    contact-sheet.jpg                  all sections side by side, for pacing review
source/
  pages/                 one HTML file per section (the editable layouts)
  styles/base.css        shared design tokens: colors, type scale, cards, bubbles
  assets/reference/      owner-supplied reference images, unchanged
  assets/product/        product scenes with the original screen artwork composited in
  assets/photos/         crops: camera close-up, character artwork, prototype photos
  fonts/                 Noto Sans SC / Noto Serif SC subsets (WOFF2, SIL OFL)
  scripts/
    build_assets.py      composites the screen artwork onto the blank plates
    render.mjs           exports each section to PNG and runs QA checks
    assemble.py          builds the long-page parts, full preview and contact sheet
    subset_fonts.py      re-subsets the fonts after copy changes
    fetch_fonts.sh       downloads the full Noto TTFs needed for re-subsetting
docs/
  PRODUCT_FACTS.md, IMAGE_ORDER.md   copied from the original handoff
CHANGELOG.md             what changed and why
```

## Reading order

01 hero → 02 comparison → 03 proactive → 04 conversation → 05 memory →
06 familiarity → 07 identity → 07a customization / MCP / open source →
08 exterior → 08a colors → 09 specifications → 10 rewards → 11 development →
12 delivery and service → 13 closing.

The exported filenames sort in this order.

## Reproducing the exports

Requirements: Python 3 with Pillow and NumPy, Node 18+.

```bash
npm install                      # installs Playwright 1.56.1
npx playwright install chromium  # skip if a Chromium build is already available
npm run build                    # assets -> render -> assemble
```

Individual steps:

```bash
python3 source/scripts/build_assets.py   # only needed if reference images change
node source/scripts/render.mjs           # all sections
node source/scripts/render.mjs 03 07a    # only sections whose filename starts with these prefixes
python3 source/scripts/assemble.py
```

`render.mjs` exits non-zero and lists the problem if a font fails to load, an
image is broken, or a text box overflows or leaves the page.

## Editing copy

Edit the text in the matching file under `source/pages/`. Page 02's seven rows
are kept in the `rows` array at the bottom of the file. The fonts are subset to the
characters currently in use. If you add new Chinese characters, re-subset the fonts:

```bash
pip install fonttools brotli
bash source/scripts/fetch_fonts.sh              # full TTFs into source/fonts/full/
python3 source/scripts/subset_fonts.py
```

## Product fidelity notes

- All product imagery comes from the supplied references. The blank plates
  (B, E, F, W) get `screen-idle-original.png` through a perspective warp onto
  the measured display corners (`SCREEN_QUADS` in `build_assets.py`). The plate's
  glass reflections are blended back on top. The artwork is never redrawn,
  re-proportioned, or cropped inside the display.
- The color page uses `front-white`, `front-lavender` and `front-pink` unchanged,
  all at the same scale, with white first.
- On the specifications page both CAD views share one scale (5 px per mm), so the
  dimension lines match 120 × 119 × 66 mm exactly.
- The prototype photos on page 11 are crops of the photos in the original page 11.
