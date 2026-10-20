# MCP frosted card trial

The reference is `exec-15ba9164-1db1-41ad-8426-f33b823e5731.png`:
a pale blue glass card, white hairline border, navy text, blue primary action
and pale secondary action above the existing subtitle dock.

## Appearance and interaction

- Card texture: 294 x 208 expanded, 294 x 116 collapsed; radius 16 px.
- New cards open expanded. Tap the body to collapse, then tap to expand.
- Header: blue bell/lock, reminder label and count of other queued reminders.
- Title uses the existing 20 px font; details and controls use the subtitle's
  existing 16 px font. Overflow ends in an ellipsis within the reserved area.
- Two 129 x 40 primary/secondary buttons; the optional third action is a
  quiet text button above them. Existing action labels are retained.
- `mcp_card_layout.h` supplies both drawing geometry and touch targets. Gaps
  and bottom padding do not activate a button.
- Current reminder instances enable their controls through `instance_id` and
  the primary label; the older `action_key` is also accepted. Actions still
  return the existing instance ID and revision to the reminder coordinator.

## Rendering and memory

Only the static wallpaper is sampled. The card's interior is opaque and
contains the blurred wallpaper, so it covers the moving character. The rest
of the scene and subtitle rendering are unchanged. The character continues
to animate; this change does not skip its rendering work.

On the first card after a wallpaper change, a 4:1 downsample and two separable
box blur passes build an 80 x 80 RGB cache (25 KiB on the 320 x 320 screen).
The temporary blur workspace is another 25 KiB and is released immediately.
Changing the wallpaper invalidates this cache and refreshes a visible card.
There is no full-screen framebuffer capture or per-frame blur.

The card uses a temporary RGB565 background (about 119 KiB expanded), an
ARGB8888 LVGL snapshot (about 239 KiB), and its final Cubicat texture (about
239 KiB). The temporary background/snapshot are released after rendering;
LVGL image cache entries are dropped before the backing memory expires.
Replacing a visible card can temporarily retain its previous texture too.
These are image-buffer estimates, excluding allocator/LVGL overhead.

The unused full-size transparent placeholder is now 1 x 1 and is released
after the first successful texture binding, saving about 239 KiB at startup.
If glass memory cannot be allocated, the same layout uses an opaque pale
blue background so reminder actions remain available.

## Device trial

No compilation or flashing was performed, as requested. Static checks covered
the available LVGL APIs, texture ownership, call signatures and touch geometry.

After flashing, compare the same role with no card, an expanded card, a
collapsed card, and a wallpaper change. Check long text and all three actions.
The first render should log `[MCPGLASS] cache=ready ... bytes=25600 build_us=...`.
Subsequent content updates reuse it. `[LVOVRENDER] kind=card style=frosted
wallpaper=1 ... render_us=...` reports total card generation time; `wallpaper=0`
means the solid fallback was used. Compare `[HOMEPERF]` and `[TASKPERF]` before
and after opening the card; buffer size alone does not predict frame rate.
