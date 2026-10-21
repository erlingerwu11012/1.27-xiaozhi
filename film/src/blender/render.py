"""Render keyframes / test frames.

blender -b -P render.py -- --shots S09 S10 --t 0.5 --pct 50 --samples 64 --out build/keyframes
"""
import argparse, math, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from mathutils import Vector
import scene, shots

ap = argparse.ArgumentParser()
ap.add_argument("--shots", nargs="+", default=list(shots.SHOTS))
ap.add_argument("--t", type=float, default=0.5)
ap.add_argument("--pct", type=int, default=100)
ap.add_argument("--samples", type=int, default=96)
ap.add_argument("--engine", default="CYCLES")
ap.add_argument("--out", default=os.path.join(scene.PROJ, "build", "keyframes"))
ap.add_argument("--save-blend", action="store_true")
ap.add_argument("--anim", action="store_true", help="render every --step frames of each shot using timeline.json lengths")
ap.add_argument("--step", type=int, default=1)
ap.add_argument("--skip-existing", action="store_true")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

ctx = scene.build_all()
shots.place_product(ctx)
# soft out-of-focus shoulder silhouette for the over-the-shoulder shot (no face, no body)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0, 0, 0))
sh = bpy.context.active_object; sh.name = "shoulder"; sh.scale = (1.6, 0.8, 0.7)
sh.data.materials.append(scene.pbr("shirt", scene.srgb("#15171a"), 0.9)); sh.data.shade_smooth()
s13 = shots.SHOTS["S13"]; c = s13["cam"][0]; d = (s13["tgt"][0] - c).normalized()
sh.location = c + d * 0.18 + Vector((0.11, 0, -0.12))
scene.setup_render(a.engine, a.samples, pct=a.pct)
a.out = os.path.abspath(a.out)
os.makedirs(a.out, exist_ok=True)
if a.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(scene.PROJ, "build", "scene.blend"))
if a.anim:
    import json
    TL = {x["id"]: x for x in json.load(open(os.path.join(scene.PROJ, "src", "timeline.json"), encoding="utf-8"))["shots"]}
    for name in a.shots:
        n = TL[name]["frames"]; dur = n / 30.0
        d = os.path.join(a.out, name); os.makedirs(d, exist_ok=True)
        t0 = time.time()
        for i in range(0, n, a.step):
            fp = os.path.join(d, f"{i:04d}.png")
            if a.skip_existing and os.path.exists(fp): continue
            shots.apply_shot(ctx, name, i / max(1, n - 1), dur=dur)
            bpy.context.scene.render.filepath = fp
            bpy.ops.render.render(write_still=True)
        print(f"[anim] {name} {n} frames step {a.step} {time.time() - t0:.1f}s", flush=True)
    sys.exit(0)
for name in a.shots:
    t0 = time.time()
    shots.apply_shot(ctx, name, a.t, keyframe=True)
    bpy.context.scene.render.filepath = os.path.join(a.out, f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"[render] {name} {time.time() - t0:.1f}s", flush=True)
