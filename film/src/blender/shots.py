"""Per-shot state: camera, light preset, screen content. Every function is pure data -> scene state.

Camera moves are defined as start/end (cam, target, lens) pairs; t in [0,1] interpolated with smoothstep.
Keyframes render at `key_t` (default 0.5).
"""
import math, os
import bpy
from mathutils import Matrix, Vector
from scene import SCREEN_DIR, PROJ, set_screen_image

PRODUCT_POS = Vector((0.30, -0.035, 0.003))
PRODUCT_YAW = -24.0          # degrees; screen turned toward the sitting user (front-left)
PC = PRODUCT_POS + Vector((0, 0, 0.062))   # product visual centre (screen centre height)


def P(dx, dy, dz):
    """offset in the PRODUCT's local frame (local -Y = in front of the screen), from the screen centre"""
    v = Vector((dx, dy, dz)); v.rotate(Matrix.Rotation(math.radians(PRODUCT_YAW), 3, "Z"))
    return PC + v


def W(x, y, z):
    """absolute world position (desk top z = 0)"""
    return Vector((x, y, z))


# ---------------------------------------------------------------- light presets
#   key/fill/rim/window are area lights, sun for morning; lamp = desk lamp spot; mon = monitor emission; screen = LCD emission
PRESETS = {
    "night_off":  dict(key=0,   fill=2,  rim=8,  window=25, win_col=(0.55, 0.68, 1.0), sun=0, lamp=0,   mon=0.35, world=0.05, screen=1.6, exposure=-0.2),
    "night_wake": dict(key=6,   fill=2,  rim=14, window=25, win_col=(0.55, 0.68, 1.0), sun=0, lamp=0,   mon=0.35, world=0.05, screen=1.6, exposure=0.0),
    "night_warm": dict(key=40,  fill=6,  rim=40, window=10, win_col=(0.55, 0.68, 1.0), sun=0, lamp=140, mon=0.8,  world=0.12, screen=1.5, exposure=0.0),
    "evening":    dict(key=90,  fill=10, rim=45, window=40, win_col=(1.0, 0.75, 0.55), sun=0, lamp=110, mon=0.9,  world=0.2,  screen=1.4, exposure=0.0),
    "lamp_dim":   dict(key=10,  fill=3,  rim=25, window=8,  win_col=(0.55, 0.68, 1.0), sun=0, lamp=10,  mon=0.5,  world=0.06, screen=1.5, exposure=0.1),
    "morning":    dict(key=25,  fill=30, rim=20, window=900, win_col=(0.72, 0.84, 1.0), sun=6.0, lamp=0, mon=0.4,  world=1.6,  screen=1.25, exposure=0.15),
    "studio":     dict(key=70, fill=14, rim=70, window=0,  win_col=(1, 1, 1),         sun=0, lamp=30,  mon=0.6,  world=0.15, screen=1.4, exposure=0.0),
}


def apply_preset(ctx, name, scale=None):
    p = dict(PRESETS[name]); p.update(scale or {})
    L = ctx["L"]
    L["key"].data.energy = p["key"]; L["fill"].data.energy = p["fill"]; L["rim"].data.energy = p["rim"]
    L["window"].data.energy = p["window"]; L["window"].data.color = p["win_col"]
    L["sun"].data.energy = p["sun"]
    bpy.data.objects["lamp_spot"].data.energy = p["lamp"]
    bpy.data.materials["bulb"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 40 * min(1, p["lamp"] / 100)
    bpy.data.materials["monitor_screen"].node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = p["mon"]
    ctx["world"].inputs["Strength"].default_value = p["world"]
    bpy.context.scene.view_settings.exposure = p["exposure"]
    return p


# ---------------------------------------------------------------- screen content
def screen(mode, t=0.0, strength=1.5):
    """mode: off | boot (t seconds, 0..2.5) | idle (t seconds into baked idle) | custom (t seconds, generated demo character)"""
    if mode == "off":
        set_screen_image(None); return
    if mode == "boot":
        f = min(74, max(0, int(t * 30)))
        set_screen_image(os.path.join(SCREEN_DIR, "boot", f"{f:03d}.png"), strength)
    elif mode == "idle":
        f = int(t * 30) % 480
        set_screen_image(os.path.join(SCREEN_DIR, "idle", f"{f:04d}.png"), strength)
    elif mode == "custom":
        f = int(t * 24) % 144
        set_screen_image(os.path.join(SCREEN_DIR, "custom", f"{f:04d}.png"), strength)
    elif mode == "boot_idle":            # original boot (2.5 s) then original wallpaper + idle
        screen("boot", t, strength) if t < 2.5 else screen("idle", t - 2.5, strength)
    elif mode == "idle_custom":          # S19: original idle, dip, then the demo character (switch at 0.7 s, before the new voice starts)
        sw = 0.7
        k = min(1.0, abs(t - sw) / 0.25)
        screen("idle", t, strength * k) if t < sw else screen("custom", t - sw, strength * k)


# ---------------------------------------------------------------- shots
# cam/target pairs are (start, end). lens mm. fstop. preset. screen=(mode, t0)
SHOTS = {
    # --- world-framed desk shots
    "S01": dict(cam=(W(-0.30, -1.25, 0.36), W(-0.22, -1.08, 0.32)), tgt=(W(0.05, 0.05, 0.10), W(0.08, 0.05, 0.10)), lens=38, fstop=4.0, focus="product", preset="night_off", scale={"exposure": 0.5}, screen=("off", 0)),
    "S12": dict(cam=(W(0.62, -0.78, 0.30), W(0.58, -0.74, 0.29)), tgt=(W(0.16, 0.05, 0.08), W(0.16, 0.05, 0.08)), lens=38, fstop=4.0, focus="product", preset="evening", screen=("idle", 5.0)),
    "S13": dict(cam=(W(-0.22, -0.72, 0.34), W(-0.20, -0.70, 0.34)), tgt=(W(0.12, 0.05, 0.10), W(0.12, 0.05, 0.10)), lens=35, fstop=3.2, focus="product", preset="night_warm", screen=("idle", 7.0), shoulder=True),
    "S14": dict(cam=(W(-0.20, -0.98, 0.42), W(-0.20, -0.98, 0.42)), tgt=(W(-0.04, 0.0, 0.17), W(-0.04, 0.0, 0.17)), lens=30, fstop=4.5, focus="product", preset="night_warm", screen=("idle", 9.0)),
    "S15": dict(cam=(W(-0.20, -0.98, 0.42), W(-0.20, -0.98, 0.42)), tgt=(W(-0.04, 0.0, 0.17), W(-0.04, 0.0, 0.17)), lens=30, fstop=4.5, focus="product", preset="lamp_dim", screen=("idle", 10.5), anim_from="night_warm", ramp=(0.18, 0.42)),
    "S21": dict(cam=(W(-0.10, -1.15, 0.40), W(-0.16, -1.35, 0.44)), tgt=(W(0.08, 0.05, 0.10), W(0.06, 0.05, 0.10)), lens=36, fstop=4.0, focus="product", preset="lamp_dim", screen=("idle", 6.0), anim_to={"lamp": 0.0, "key": 3, "rim": 12}, ramp_to=(0.31, 0.34)),
    # --- product-local shots (local -Y = in front of the screen)
    "S08": dict(cam=(P(-0.17, -0.19, 0.012), P(-0.15, -0.21, 0.018)), tgt=(P(-0.012, 0.0, -0.010), P(-0.004, 0.0, -0.006)), lens=60, fstop=2.8, focus="product", preset="night_wake", screen=("boot_idle", 0.0), key_screen=("boot", 0.9)),
    "S09": dict(cam=(P(-0.07, -0.17, 0.005), P(-0.21, -0.44, 0.10)), tgt=(P(0, 0, 0), P(-0.01, 0, -0.005)), lens=50, fstop=2.8, focus="product", preset="night_warm", screen=("idle", 1.0), anim_from="night_wake", ramp=(0.18, 0.42)),
    "S10": dict(cam=(P(-0.20, -0.46, 0.08), P(-0.22, -0.45, 0.08)), tgt=(P(-0.12, 0, -0.005), P(-0.12, 0, -0.005)), lens=50, fstop=2.8, focus="product", preset="night_warm", screen=("idle", 3.0)),
    "S16": dict(cam=(P(0.17, -0.40, 0.10), P(0.16, -0.38, 0.10)), tgt=(P(-0.06, 0, 0.0), P(-0.06, 0, 0.0)), lens=50, fstop=2.8, focus="product", preset="lamp_dim", screen=("idle", 11.5)),
    "S17": dict(cam=(P(0.17, -0.40, 0.10), P(0.16, -0.38, 0.10)), tgt=(P(-0.06, 0, 0.0), P(-0.06, 0, 0.0)), lens=50, fstop=2.8, focus="product", preset="morning", screen=("idle", 13.0)),
    "S18": dict(cam=(P(0.44, -0.28, 0.07), P(0.42, -0.31, 0.07)), tgt=(P(0.05, 0.0, -0.008), P(0.05, 0.0, -0.008)), lens=55, fstop=2.8, focus="product", preset="studio", screen=("idle", 2.0)),
    "S19": dict(cam=(P(-0.03, -0.44, 0.014), P(-0.027, -0.40, 0.012)), tgt=(P(0, 0, -0.006), P(0, 0, -0.006)), lens=65, fstop=3.5, focus="product", preset="night_warm", screen=("idle_custom", 0.0), key_screen=("custom", 1.0)),
    "S20": dict(cam=(P(0.30, 0.38, 0.11), P(0.38, 0.26, 0.11)), tgt=(P(-0.03, 0, -0.012), P(-0.03, 0, -0.012)), lens=55, fstop=3.2, focus="product", preset="studio", screen=("idle", 4.0)),
    "S22": dict(cam=(P(0.0, -0.78, 0.09), P(0.0, -0.88, 0.10)), tgt=(P(0, 0, 0.048), P(0, 0, 0.055)), lens=50, fstop=2.8, focus="product", preset="lamp_dim", screen=("idle", 8.0)),
}


def smooth(t):
    return t * t * (3 - 2 * t)


def place_product(ctx):
    pr = ctx["product"]
    pr.location = PRODUCT_POS
    pr.rotation_euler = (0, 0, math.radians(PRODUCT_YAW))


def _blend(a, b, k):
    return {key: (tuple(x + (y - x) * k for x, y in zip(a[key], b[key])) if isinstance(a[key], tuple) else a[key] + (b[key] - a[key]) * k) for key in a}


def _ramp(t, ab):
    a, b = ab
    return smooth(min(1.0, max(0.0, (t - a) / (b - a))))


def apply_shot(ctx, name, t=0.5, extra_preset=None, dur=4.0, keyframe=False):
    s = SHOTS[name]
    u = smooth(t)
    cam, tgt = ctx["cam"], ctx["target"]
    cam.location = s["cam"][0].lerp(s["cam"][1], u)
    tgt.location = s["tgt"][0].lerp(s["tgt"][1], u)
    cam.data.lens = s["lens"]
    cam.data.dof.aperture_fstop = s["fstop"]
    if s.get("focus") == "product":
        cam.data.dof.focus_object = None
        cam.data.dof.focus_distance = (cam.location - PC).length
    else:
        cam.data.dof.focus_object = tgt
    card = ctx["L"]["refl_card"]
    back = (cam.location - PC); back.z = 0; back.normalize()
    card.location = PC + back * 0.9 + Vector((0, 0, 0.55))
    card.rotation_euler = (PC - card.location).to_track_quat("Z", "Y").to_euler()
    card.rotation_euler.rotate_axis("X", math.radians(180))
    ctx["L"]["sun"].rotation_euler = (math.radians(66), 0, math.radians(-52 if s["preset"] == "morning" else -78))
    over = {**s.get("scale", {}), **(extra_preset or {})}
    if not keyframe and "anim_from" in s:
        base = {**PRESETS[s["anim_from"]], **over}; tgt_p = {**PRESETS[s["preset"]], **over}
        over = _blend(base, tgt_p, _ramp(t, s["ramp"]))
    if not keyframe and "anim_to" in s:
        base = {**PRESETS[s["preset"]], **over}
        over = _blend(base, {**base, **s["anim_to"]}, _ramp(t, s["ramp_to"]))
    p = apply_preset(ctx, s["preset"], over)
    mode, t0 = s.get("key_screen", s["screen"]) if keyframe else s["screen"]
    screen(mode, t0 + t * dur, p["screen"])
    bpy.data.objects["shoulder"].hide_render = not s.get("shoulder", False)
    return s
