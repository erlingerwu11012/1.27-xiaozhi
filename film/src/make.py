"""One-command rebuild of the promo film.

  python make.py proxy     # 640x360, every 3rd frame rendered (held x3), Cycles 16 spp  -> output/proxy_preview.mp4
  python make.py final     # 1920x1080, every frame, Cycles 40 spp (~15-16 h on GTX 1650)                     -> output/xiaonian_promo_v2.mp4
  python make.py final --shots S09,S10   # re-render only some 3D shots, then recomposite and re-encode
  python make.py audio     # remix only (after replacing any file in audio/vo, audio/music, audio/sfx)

Paid generation (voices, music, SFX, plates, demo character) is NOT re-run here; those files are already on disk.
To regenerate one: src/audio/synth_voices.py make L14   |   src/audio/gen_music_sfx.py make cueB_warm
"""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
BLENDER = os.environ.get("BLENDER_PATH") or __import__("shutil").which("blender") or "blender"
PY = sys.executable
SHOTS_3D = ["S01", "S08", "S09", "S10", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19", "S20", "S21", "S22"]


def run(cmd, **kw):
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["proxy", "final", "audio"])
    ap.add_argument("--shots", default="")
    ap.add_argument("--no-render", action="store_true", help="skip Blender, reuse existing 3D frames")
    a = ap.parse_args()
    proxy = a.mode == "proxy"
    run([PY, os.path.join(HERE, "timeline.py")])
    if not os.path.isdir(os.path.join(PROJ, "build", "screen", "idle")):
        run(["node", os.path.join(HERE, "screen", "bake.mjs"), "16", "30"])
    run([PY, os.path.join(HERE, "audio", "mix.py")])
    if a.mode == "audio":
        return
    src3d = "build/proxy3d" if proxy else "build/final3d"
    frames = "build/proxy_frames" if proxy else "build/final_frames"
    step, pct, spp = (3, 34, 16) if proxy else (1, 100, 40)   # 40 spp + OIDN: same look as 128 spp at ~24 s/frame on a GTX 1650
    shots = a.shots.split(",") if a.shots else SHOTS_3D
    if not a.no_render:
        extra = [] if a.shots else ["--skip-existing"]
        run([BLENDER, "-b", "-P", os.path.join(HERE, "blender", "render.py"), "--", "--anim", "--step", str(step), "--pct", str(pct),
             "--samples", str(spp), "--out", os.path.join(PROJ, src3d), *extra, "--shots", *shots])
    run(["node", os.path.join(HERE, "compositor", "film.mjs"), "--scale", "0.3333" if proxy else "1", "--step", str(step), "--src", src3d, "--out", frames])
    os.makedirs(os.path.join(PROJ, "output"), exist_ok=True)
    out = os.path.join(PROJ, "output", "proxy_preview.mp4" if proxy else "xiaonian_promo_v2.mp4")
    fr = os.path.join(PROJ, frames)
    # frames are named by their absolute frame number; proxy has every 3rd -> play at 10 fps, output 30 fps
    lst = os.path.join(fr, "_list.txt")
    files = sorted(f for f in os.listdir(fr) if f.endswith(".jpg"))
    with open(lst, "w", encoding="utf-8") as f:
        for name in files:
            f.write(f"file '{name}'\nduration {step / 30:.6f}\n")
        f.write(f"file '{files[-1]}'\n")
    vf = "fps=30,format=yuv420p" if proxy else "fps=30,noise=alls=3:allf=t,format=yuv420p"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", os.path.join(PROJ, "audio", "mix", "final_mix.wav"),
         "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "23" if proxy else "17", "-maxrate", "16M" if not proxy else "4M", "-bufsize", "24M",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", out])
    print("done:", out)


if __name__ == "__main__":
    main()
