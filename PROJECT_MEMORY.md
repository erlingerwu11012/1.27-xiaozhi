# Desktop Companion Film - Continuation Memory

The editable project is in `film/`. Read `README.md` and `CONTINUE.md` at the repository root before making changes.

Current state:
- A storyboard, shot keyframes, voice-over, music, sound effects, and a low-resolution proxy preview exist.
- The preview is `film/output/proxy_preview.mp4`. It is a review draft, not an approved final film.
- A full-resolution final render has not been produced in this project snapshot.
- The user wants substantial revisions. Inspect the existing preview and ask for the requested changes before spending time on a full render.

Working files:
- `film/src/lines.json`: spoken lines and voice assignments.
- `film/src/timeline.py` and `film/src/timeline.json`: edit timing.
- `film/src/blender/`: product geometry, set, cameras, and rendering.
- `film/src/screen/`: original screen artwork, startup sequence, and idle animation baking.
- `film/src/compositor/`: captions, dialogue bubbles, and compositing.
- `film/audio/`: existing recorded and generated audio.
- `film/storyboard/`: shot review images and review page.

Requirements:
- Keep the film's existing spoken language and on-screen copy unless the user requests a change.
- Preserve the real hardware geometry, assembly, colors, bezel, screen layout, original wallpaper, and original idle character.
- The custom-character example is a demonstration asset, not a replacement for the original character.
- Use stable three-dimensional camera movement and visually review a short sample before a full render.
- Existing media can be reused without generating it again. Do not start paid generation automatically; obtain approval for any batch exceeding 50 credits.
- When calling the generation CLI from a script, use `stdin=subprocess.DEVNULL` to avoid an input stall.
- Keep revisions separate from the original files and report what was actually rendered and verified.
