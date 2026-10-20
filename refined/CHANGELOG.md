# Change log

## Whole page

- Rebuilt every section as editable HTML/CSS on a 1440 px grid with 96 px gutters.
  A single type system is now used throughout: Noto Serif SC for headlines and titles,
  Noto Sans SC for body text. The original page 07a fell back to a different serif and
  used a monospace MCP heading; that inconsistency is gone.
- Raised the minimum text size to about 26–28 px and body text to 30–36 px, so copy
  stays legible when the 1440 px images are shown at phone width. Body copy contrast
  was raised from light gray to a darker gray-blue.
- Rebalanced background rhythm. The original had long runs of the same off-white.
  The sequence now alternates warm off-white, warm stone, pale blue and gray-blue:
  01 photo · 02 paper · 03 pale blue · 04 paper · 05 stone · 06 paper with full-bleed
  photo · 07 gray-blue · 07a paper · 08 stone with full-bleed photo · 08a pale blue ·
  09 paper · 10 stone · 11 paper · 12 pale blue · 13 photo. No dark green is used.
- Varied composition between neighboring sections: full-bleed photo bands (06, 08),
  split zig-zag cards (05), a featured card (10), a timeline (11) and a centered
  closing.
- Added no eyebrow labels, page counters, bottom slogans, disclaimers or
  comparison caveats. No pricing appears outside page 10.

## Product imagery

- Product scenes are re-composited from the blank plates and the original screen artwork.
  The plates' reflections are kept and the geometry is untouched.
- Each scene is used for a distinct job. Plate B is the hero, F is page 03 and the
  camera close-up on 07, B/E crops are on 05, the wide W scene is on 06, M is on 08,
  and E is the closing. Before, 01, 05 and 06 all used the same B framing.
- 13: the hard-edged, faded photo rectangle was replaced by a full-bleed scene that
  fades into the headline area.

## Section notes

- 01: Larger headline. The three feature words now sit on a frosted bar so they stay
  readable over the desk.
- 02: Structure kept: seven rows, two columns, same row order and wording.
  Typography and contrast were refined, the "小念" column is emphasized, and arrows
  sit in small circles. **Copy fix:** row 6 said 音色、角色立绘、外壳配色，以及工具等，都支持自定义.
  Enclosure color is not software customization, so it now reads
  音色与角色立绘可自定义，还能通过 MCP 接入工具。
- 03: Photo card reframed so the whole device is visible. The radar → identify → greet
  steps sit on one card.
- 04: Chat bubbles separate the two speakers by color. The Harness note became an
  icon callout.
- 05: "几天前 / 几天后" are now two alternating split cards (daylight, then evening)
  joined by a dashed connector.
- 06: The photo became a full-bleed band. The quote sits on the wall area.
- 07: Camera close-up recropped around the actual camera opening, with a focus ring.
- 07a: Customization, MCP and open source stay on one page. MCP flow diagram added,
  and open source got its own card.
- 08: The knob close-up is now edge to edge. White and graphite swatches were added
  to the two-tone point.
- 08a: Shadows and labelled swatches added; lavender and pink sit on light cards.
- 09: Dimension lines (120 / 119 / 66 mm) added to the CAD views at true scale.
- 10: Prices, quantities and contents unchanged. The super early bird tier is the
  featured card, and all cards share one height. **Naming fix:** the 399 and 409
  tiers said 小念桌面助手 while the 369 tier said 小念桌面陪伴助手. All three now use
  小念桌面陪伴助手.
- 11: Completed work shown as a checked 2 × 2 grid. Launch and dispatch dates sit
  on a timeline.
- 12: Billing card and service rows restyled. Wording unchanged.
- 13: **Consistency fix:** the closing feature words (主动对话 / 自然交流 / 永久记忆)
  now match the hero (主动交互 / 自然对话 / 永久记忆).

## Verification performed

- Rendered all 15 sections with the automated checks in `render.mjs`: fonts loaded,
  images decoded, no overflowing or off-page text. All passed.
- Confirmed the subset fonts contain every character used; renders are
  pixel-identical to renders made with the full fonts.
- Extracted the rendered text of every section and proofread it against the
  original images.
- Visually inspected every exported section and the assembled long page.
