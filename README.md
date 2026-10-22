# Desktop Companion Film Handoff

Start with `CLAUDE.md`, `CONTINUE.md`, and `film/output/proxy_preview.mp4`.

This branch contains a review draft and editable production materials. The preview is 640 x 360. A finished full-resolution film is not included. The user wants revisions; do not assume the current draft is approved.

## Contents

- `film/output/proxy_preview.mp4`: existing preview, unchanged.
- `film/storyboard/index.html` and `film/storyboard/keyframes/`: visual review materials.
- `film/storyboard_v2.md`: original creative storyboard.
- `film/src/`: Blender scenes, shot definitions, screen animation, compositor, timing, and audio tools.
- `film/audio/`: voice-over, music, effects, and the existing final mix.
- `film/assets/`: original geometry, screen assets, boot sequence, and font.
- `film/plates/` and `film/custom-character/`: existing creative media.
- `film/build/`: product screen bounds and keyframe renders used by the storyboard compositor.

Original creative files retain the existing language.

## Local use

Clone this branch and open the MP4 in a media player. No server is needed to watch it.

To continue editing, install Python with numpy, scipy, and soundfile; Node.js; FFmpeg; Blender; and a supported browser. Run `npm ci` inside `film/src`. Set `BLENDER_PATH` and `BROWSER_PATH` if the programs are not discoverable. The source copy uses bundled assets rather than unrelated local folders.

Commands from `film/src`:

```sh
python make.py audio
python make.py proxy
python make.py final --shots S09,S10
```

Paid media generation is separate and is not triggered by the rebuild command. Generated frame caches and installed software are excluded. Re-rendering requires the listed tools. This package has been checked for file integrity and source syntax; it has not been fully re-rendered after relocation.
