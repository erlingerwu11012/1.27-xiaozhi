"""Export each shot's product bounding box in screen space (0..1920 x 0..1080) -> build/product_screen.json.
Overlays (dialog boxes, captions, sensing ring) use it to stay clear of the product."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
import scene, shots

ctx = scene.build_all(); shots.place_product(ctx)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.01); bpy.context.active_object.name = "shoulder"
sc = bpy.context.scene; sc.render.resolution_x, sc.render.resolution_y = 1920, 1080
t = float(sys.argv[sys.argv.index("--") + 1]) if "--" in sys.argv else 0.5
out = {}
parts = [o for o in ctx["product"].children if o.type == "MESH"]
for name in shots.SHOTS:
    shots.apply_shot(ctx, name, t); bpy.context.view_layer.update()
    xs, ys = [], []
    for o in parts:
        for c in o.bound_box:
            p = world_to_camera_view(sc, ctx["cam"], o.matrix_world @ Vector(c))
            xs.append(p.x * 1920); ys.append((1 - p.y) * 1080)
    base = world_to_camera_view(sc, ctx["cam"], ctx["product"].matrix_world.translation)
    out[name] = dict(bbox=[round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))], base=[round(base.x * 1920), round((1 - base.y) * 1080)])
json.dump(out, open(os.path.join(scene.PROJ, "build", "product_screen.json"), "w"), indent=1)
print(json.dumps(out))
