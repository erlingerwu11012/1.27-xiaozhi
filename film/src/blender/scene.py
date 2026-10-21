"""Procedural dark computer-desk set + the real CAD product, built entirely from Python in Blender 4.5.

Units: metres. Desk top surface at z = 0. Camera-facing side of the desk is -Y.
Product: parts-data.json (mm, Y-up, screen faces +Z) -> one common transform
(uniform 0.001 scale + axis swap + placement). No per-part centring or scaling.
"""
import base64, json, math, os
import bpy, bmesh
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, "..", ".."))
OUTPUTS = os.path.abspath(os.path.join(PROJ, ".."))
MAT_DIR = os.path.join(PROJ, "assets")
SCREEN_DIR = os.path.join(PROJ, "build", "screen")

# ---------------------------------------------------------------- helpers

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def link(ob, coll=None):
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def mesh_obj(name, bm, mat=None, smooth=False, parent=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.shade_smooth()
    ob = link(bpy.data.objects.new(name, me))
    if mat:
        me.materials.append(mat)
    if parent:
        ob.parent = parent
    return ob


def box(name, size, loc, mat=None, bevel=0.0, segs=3, parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    ob = mesh_obj(name, bm, mat, parent=parent)
    ob.location = loc
    if bevel:
        m = ob.modifiers.new("bevel", "BEVEL")
        m.width, m.segments, m.limit_method = bevel, segs, "ANGLE"
        m.harden_normals = True
        ob.data.shade_smooth()
    return ob


def cyl(name, r, h, loc, mat=None, verts=64, bevel=0.0, parent=None, r2=None, cap=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=cap, segments=verts, radius1=r, radius2=r if r2 is None else r2, depth=h)
    ob = mesh_obj(name, bm, mat, parent=parent)
    ob.location = loc
    ob.data.shade_smooth()
    if bevel:
        m = ob.modifiers.new("bevel", "BEVEL")
        m.width, m.segments, m.limit_method = bevel, 3, "ANGLE"
        m.harden_normals = True
    return ob


def node_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    return m, nt, bsdf


def pbr(name, color, rough=0.5, metal=0.0, coat=0.0, sss=0.0, spec=0.5):
    m, nt, b = node_mat(name)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Specular IOR Level"].default_value = spec
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.08
    if sss:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (0.6, 0.5, 0.45)
        b.inputs["Subsurface Scale"].default_value = 0.002
    return m


def srgb(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)

# ---------------------------------------------------------------- materials

def mat_resin_white():
    # matte white resin: slight SSS, fine micro-bump so highlights break up like real print/paint
    m, nt, b = node_mat("resin_white")
    b.inputs["Base Color"].default_value = (*srgb("#e9e7e2"), 1)
    b.inputs["Roughness"].default_value = 0.52
    b.inputs["Subsurface Weight"].default_value = 0.12
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.85, 0.7)
    b.inputs["Subsurface Scale"].default_value = 0.0015
    n = nt.nodes.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = 2200; n.inputs["Detail"].default_value = 2
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.035; bump.inputs["Distance"].default_value = 0.0002
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_graphite():
    m, nt, b = node_mat("graphite")
    b.inputs["Base Color"].default_value = (*srgb("#3b3e42"), 1)
    b.inputs["Roughness"].default_value = 0.46
    b.inputs["Specular IOR Level"].default_value = 0.45
    n = nt.nodes.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = 1800; n.inputs["Detail"].default_value = 2
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.04; bump.inputs["Distance"].default_value = 0.0002
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def mat_wood(name="walnut", dark=1.0):
    m, nt, b = node_mat(name)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0, 14.0, 1.0)
    w = nt.nodes.new("ShaderNodeTexWave"); w.wave_type = "RINGS"; w.inputs["Scale"].default_value = 3.0
    w.inputs["Distortion"].default_value = 9.0; w.inputs["Detail"].default_value = 4; w.inputs["Detail Scale"].default_value = 1.5
    n = nt.nodes.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = 60
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*[c * dark for c in srgb("#1d130d")], 1)
    ramp.color_ramp.elements[1].color = (*[c * dark for c in srgb("#4a3121")], 1)
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "FLOAT"; mix.inputs["Factor"].default_value = 0.25
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], w.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], n.inputs["Vector"])
    nt.links.new(w.outputs["Fac"], mix.inputs["A"]); nt.links.new(n.outputs["Fac"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    rr = nt.nodes.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = 0.32; rr.inputs["To Max"].default_value = 0.5
    nt.links.new(mix.outputs["Result"], rr.inputs["Value"]); nt.links.new(rr.outputs["Result"], b.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.08
    nt.links.new(mix.outputs["Result"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Coat Weight"].default_value = 0.25; b.inputs["Coat Roughness"].default_value = 0.25
    return m


def mat_noise(name, c1, c2, rough, scale=40, bump_s=0.15, sheen=0.0):
    m, nt, b = node_mat(name)
    n = nt.nodes.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = scale; n.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*srgb(c1), 1); ramp.color_ramp.elements[1].color = (*srgb(c2), 1)
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    bump = nt.nodes.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = bump_s
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"]); nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    if sheen:
        b.inputs["Sheen Weight"].default_value = sheen
    return m


def mat_emit_image(name, path, strength=1.0, gloss=True):
    """Screen: glossy black glass with the image as emission (reflections sit on top naturally)."""
    m, nt, b = node_mat(name)
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.name = "screen_tex"
    tex.interpolation = "Cubic"; tex.extension = "CLIP"
    if path:
        img = bpy.data.images.load(path, check_existing=True)
        tex.image = img
    b.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1)
    b.inputs["Roughness"].default_value = 0.035 if gloss else 0.4
    b.inputs["Specular IOR Level"].default_value = 0.55
    b.inputs["Coat Weight"].default_value = 1.0 if gloss else 0.0
    b.inputs["Coat Roughness"].default_value = 0.02
    nt.links.new(tex.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = strength
    return m

# ---------------------------------------------------------------- product (real CAD)

PART_MAT = {"front": "white", "left_knob": "white", "right_knob": "white", "buttons": "white_btn",
            "rear": "graphite", "base": "graphite", "left_support": "graphite", "right_support": "graphite"}

# data (x, y, z) mm, Y-up, screen +Z  ->  blender (x, -z, y) m, Z-up, screen faces -Y. Base bottom (y=-67) -> z=0.
AXIS = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0.067), (0, 0, 0, 1))) @ Matrix.Scale(0.001, 4)


def build_product(mats):
    root = link(bpy.data.objects.new("PRODUCT", None))
    parts = json.load(open(os.path.join(MAT_DIR, "models", "parts-data.json")))
    import array
    for p in parts:
        pos = array.array("f"); pos.frombytes(base64.b64decode(p["positions"]))
        nor = array.array("f"); nor.frombytes(base64.b64decode(p["normals"]))
        idx = array.array("I"); idx.frombytes(base64.b64decode(p["indices"]))
        nv, nt = len(pos) // 3, len(idx) // 3
        me = bpy.data.meshes.new(p["name"])
        me.vertices.add(nv); me.vertices.foreach_set("co", pos)
        me.loops.add(nt * 3); me.loops.foreach_set("vertex_index", idx)
        me.polygons.add(nt); me.polygons.foreach_set("loop_start", range(0, nt * 3, 3))
        me.update(calc_edges=True); me.validate(clean_customdata=False)
        me.shade_smooth()
        ns = [tuple(nor[i * 3:i * 3 + 3]) for i in range(nv)]
        me.normals_split_custom_set_from_vertices(ns)
        me.transform(AXIS)          # one shared transform for every part (keeps original assembly)
        ob = link(bpy.data.objects.new(p["name"], me)); ob.parent = root
        me.materials.append(mats[PART_MAT.get(p["name"], "graphite")])
    # --- screen stack from dimensions.json screen_insert (display face z = 14.11 mm in data coords)
    def P(x, y, z):  # data mm -> blender m
        return AXIS @ Vector((x, y, z))
    zf = 14.11
    # black cover glass 84x84 (thick black margins come from this glass around the LCD active area)
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    cover = mesh_obj("screen_cover", bm, mats["glass_black"], parent=root)
    cover.matrix_world = Matrix.Translation(P(0, 0, zf + 0.02)) @ Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Diagonal((0.084, 0.084, 1, 1))
    # LCD active area 71.14 x 69.82, offset +1.0 mm (up) from cover centre
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x + 0.5, l.vert.co.y + 0.5)
    lcd = mesh_obj("screen_lcd", bm, mats["screen"], parent=root)
    lcd.matrix_world = Matrix.Translation(P(0, 1.0, zf + 0.04)) @ Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Diagonal((0.07114, 0.06982, 1, 1))
    return root


def set_screen_image(path, strength=None):
    m = bpy.data.materials["screen"]
    tex = m.node_tree.nodes["screen_tex"]
    if path is None:
        tex.image = None
        m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 0.0
        return
    old = tex.image
    tex.image = bpy.data.images.load(path, check_existing=True)
    if old is not None and old != tex.image and old.users == 0:
        bpy.data.images.remove(old)          # keep memory flat when stepping through image sequences
    if strength is not None:
        m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = strength

# ---------------------------------------------------------------- desk set

def build_desk(mats):
    S = {}
    walnut = mats["walnut"]
    S["desk"] = box("desk_top", (1.7, 0.78, 0.032), (0, 0.0, -0.016), walnut, bevel=0.004)
    box("desk_leg_l", (0.05, 0.7, 0.72), (-0.78, 0.0, -0.39), mats["graphite_dark"], bevel=0.003)
    box("desk_leg_r", (0.05, 0.7, 0.72), (0.78, 0.0, -0.39), mats["graphite_dark"], bevel=0.003)
    # felt/leather desk mat
    S["mat"] = box("desk_mat", (0.86, 0.38, 0.003), (0.02, -0.11, 0.0015), mats["mat"], bevel=0.0012, segs=2)
    # back wall + walnut slat panel
    box("wall", (4.0, 0.05, 2.4), (0, 0.62, 0.6), mats["wall"])
    slat = mats["walnut_dark"]
    for i in range(34):
        box(f"slat_{i}", (0.026, 0.02, 1.1), (-0.76 + i * 0.046, 0.585, 0.45), slat, bevel=0.002, segs=2)
    # monitor (27", thin) on a stand
    mon = link(bpy.data.objects.new("MONITOR", None)); mon.location = (-0.04, 0.27, 0)
    box("mon_foot", (0.24, 0.17, 0.008), (0, 0.02, 0.004), mats["graphite_dark"], bevel=0.003, parent=mon)
    box("mon_neck", (0.05, 0.025, 0.28), (0, 0.07, 0.15), mats["graphite_dark"], bevel=0.004, parent=mon)
    box("mon_body", (0.615, 0.03, 0.365), (0, 0.045, 0.335), mats["bezel"], bevel=0.004, parent=mon)
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for l in f.loops:
            l[uv].uv = (l.vert.co.x + 0.5, l.vert.co.y + 0.5)
    ms = mesh_obj("mon_screen", bm, mats["monitor_screen"], parent=mon)
    ms.matrix_parent_inverse = Matrix()
    ms.location = (0, 0.0295, 0.339); ms.rotation_euler = (math.radians(90), 0, 0); ms.scale = (0.597, 0.336, 1)
    S["monitor"] = mon
    # low-profile keyboard
    kb = link(bpy.data.objects.new("KEYBOARD", None)); kb.location = (-0.07, -0.12, 0.003); kb.rotation_euler = (0, 0, math.radians(1.5))
    box("kb_case", (0.355, 0.125, 0.016), (0, 0, 0.008), mats["kb_case"], bevel=0.003, parent=kb)
    bm = bmesh.new(); u = 0.0185
    rows = [[1] * 14 + [1.5], [1.5] + [1] * 12 + [1.5], [1.75] + [1] * 11 + [2.25], [2.25] + [1] * 10 + [2.75], [1.25] * 3 + [6.25] + [1.25] * 4]
    for r, row in enumerate(rows):
        x = -0.165
        for w in row:
            wm = w * u
            g = bmesh.ops.create_cube(bm, size=1.0)
            vs = g["verts"]
            bmesh.ops.scale(bm, vec=(wm - 0.0025, u - 0.0025, 0.007), verts=vs)
            bmesh.ops.translate(bm, vec=(x + wm / 2, 0.045 - r * u, 0.0185), verts=vs)
            x += wm
    caps = mesh_obj("kb_caps", bm, mats["keycap"], parent=kb)
    mb = caps.modifiers.new("bevel", "BEVEL"); mb.width = 0.0011; mb.segments = 2; mb.harden_normals = True
    caps.data.shade_smooth()
    # brass architect lamp (left, behind keyboard)
    lamp = link(bpy.data.objects.new("LAMP", None)); lamp.location = (-0.56, 0.2, 0); lamp.rotation_euler = (0, 0, math.radians(35))
    brass = mats["brass"]
    cyl("lamp_base", 0.075, 0.016, (0, 0, 0.008), mats["graphite_dark"], bevel=0.003, parent=lamp)
    cyl("lamp_post", 0.007, 0.38, (0, 0, 0.2), brass, parent=lamp)
    arm = cyl("lamp_arm", 0.006, 0.36, (0.0, -0.13, 0.42), brass, parent=lamp); arm.rotation_euler = (math.radians(-62), 0, 0)
    shade = cyl("lamp_shade", 0.075, 0.12, (0, -0.29, 0.36), mats["lamp_shade"], r2=0.022, cap=False, parent=lamp)
    shade.rotation_euler = (math.radians(-25), 0, 0)
    sol = shade.modifiers.new("solid", "SOLIDIFY"); sol.thickness = 0.0015
    bulb = cyl("lamp_bulb", 0.022, 0.02, (0, -0.295, 0.335), mats["bulb"], parent=lamp)
    ld = bpy.data.lights.new("lamp_spot", "SPOT"); ld.energy = 30; ld.spot_size = math.radians(95); ld.spot_blend = 0.75
    ld.shadow_soft_size = 0.03; ld.color = (1.0, 0.68, 0.40)
    lo = link(bpy.data.objects.new("lamp_spot", ld)); lo.parent = lamp; lo.location = (0, -0.29, 0.34); lo.rotation_euler = (math.radians(-25), 0, 0)
    S["lamp"] = lamp
    # snake plant in a ceramic pot (right back)
    pot = link(bpy.data.objects.new("PLANT", None)); pot.location = (0.62, 0.25, 0)
    p = cyl("pot", 0.065, 0.13, (0, 0, 0.065), mats["ceramic_dark"], bevel=0.004, parent=pot, r2=0.055)
    cyl("soil", 0.058, 0.004, (0, 0, 0.122), mats["soil"], parent=pot)
    import random
    random.seed(7)
    for i in range(16):
        h = random.uniform(0.22, 0.42); wdt = random.uniform(0.022, 0.034)
        bm = bmesh.new(); n = 10
        prev = None
        vs = []
        for k in range(n + 1):
            t = k / n
            ww = wdt * (1 - t ** 2.2) * (0.7 + 0.3 * math.sin(t * math.pi))
            tw = 0.6 * t
            for sgn in (-1, 1):
                vs.append(bm.verts.new((sgn * ww * math.cos(tw), sgn * ww * math.sin(tw) + 0.01 * t * t, h * t)))
        for k in range(n):
            a, b, c, d = vs[2 * k], vs[2 * k + 1], vs[2 * k + 3], vs[2 * k + 2]
            bm.faces.new((a, b, c, d))
        leaf = mesh_obj(f"leaf_{i}", bm, mats["leaf"], smooth=True, parent=pot)
        so = leaf.modifiers.new("s", "SOLIDIFY"); so.thickness = 0.002
        ang = i / 16 * math.tau + random.uniform(-0.3, 0.3)
        r0 = random.uniform(0.0, 0.03)
        leaf.location = (r0 * math.cos(ang), r0 * math.sin(ang), 0.12)
        leaf.rotation_euler = (random.uniform(-0.25, 0.25), random.uniform(-0.25, 0.25), ang)
    S["plant"] = pot
    # ceramic mug
    mug = link(bpy.data.objects.new("MUG", None)); mug.location = (-0.37, -0.17, 0.0)
    m = cyl("mug_body", 0.04, 0.092, (0, 0, 0.046), mats["ceramic_light"], cap=False, parent=mug)
    bm = m.data
    so = m.modifiers.new("s", "SOLIDIFY"); so.thickness = 0.004; so.offset = -1
    cyl("mug_bottom", 0.04, 0.006, (0, 0, 0.003), mats["ceramic_light"], parent=mug)
    cyl("coffee", 0.036, 0.002, (0, 0, 0.078), mats["coffee"], parent=mug)
    bm2 = bmesh.new(); bmesh.ops.create_circle(bm2, segments=24, radius=0.022)
    tor = mesh_obj("mug_handle_path", bm2, None, parent=mug)
    bpy.data.objects.remove(tor)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.022, minor_radius=0.0055, location=(0.045, 0, 0.05), rotation=(math.radians(90), 0, 0))
    h = bpy.context.active_object; h.name = "mug_handle"; h.parent = mug; h.location = (0.045, 0, 0.05); h.scale = (0.8, 1, 1)
    h.data.materials.append(mats["ceramic_light"]); h.data.shade_smooth()
    S["mug"] = mug
    # small book stack (left of monitor)
    bk = link(bpy.data.objects.new("BOOKS", None)); bk.location = (-0.36, 0.13, 0); bk.rotation_euler = (0, 0, math.radians(8))
    for i, (c, th) in enumerate([("#2a3440", 0.028), ("#5a4632", 0.022), ("#1c1c1e", 0.025)]):
        box(f"book_{i}", (0.2 - i * 0.012, 0.145 - i * 0.008, th), (0, 0, sum([0.028, 0.022, 0.025][:i]) + th / 2), pbr(f"book_{i}", srgb(c), 0.7), bevel=0.0015, parent=bk)
    return S


def make_materials():
    M = {}
    M["white"] = mat_resin_white()
    M["white_btn"] = pbr("white_btn", srgb("#dedcd6"), 0.45)
    M["graphite"] = mat_graphite()
    M["graphite_dark"] = pbr("graphite_dark", srgb("#232427"), 0.42, metal=0.6)
    M["glass_black"] = mat_emit_image("glass_black", None, 0.0)
    M["screen"] = mat_emit_image("screen", None, 1.0)
    M["walnut"] = mat_wood("walnut", 1.0)
    M["walnut_dark"] = mat_wood("walnut_dark", 0.7)
    M["mat"] = mat_noise("desk_mat", "#0f1012", "#16171a", 0.78, scale=900, bump_s=0.04, sheen=0.15)
    M["wall"] = mat_noise("wall", "#1c1b1a", "#24221f", 0.92, scale=8, bump_s=0.08)
    bs = M["mat"].node_tree.nodes["Principled BSDF"]; bs.inputs["Specular IOR Level"].default_value = 0.25; bs.inputs["Roughness"].default_value = 0.88
    M["bezel"] = pbr("bezel", srgb("#0d0d0e"), 0.35)
    M["kb_case"] = pbr("kb_case", srgb("#2b2c2f"), 0.38, metal=0.7)
    M["keycap"] = pbr("keycap", srgb("#3a3b3e"), 0.62)
    M["brass"] = pbr("brass", srgb("#b8925a"), 0.28, metal=1.0)
    M["lamp_shade"] = pbr("lamp_shade", srgb("#1f2022"), 0.4, metal=0.5)
    b, nt, bs = node_mat("bulb"); bs.inputs["Emission Color"].default_value = (1.0, 0.72, 0.45, 1); bs.inputs["Emission Strength"].default_value = 40; M["bulb"] = b
    M["ceramic_dark"] = mat_noise("ceramic_dark", "#3a3633", "#46413c", 0.7, scale=300, bump_s=0.05)
    M["ceramic_light"] = pbr("ceramic_light", srgb("#d9d4cc"), 0.35, coat=0.3)
    M["soil"] = mat_noise("soil", "#120d0a", "#2a1d14", 0.95, scale=400, bump_s=0.4)
    M["coffee"] = pbr("coffee", srgb("#1b0f08"), 0.08)
    M["leaf"] = mat_noise("leaf", "#13241a", "#34502c", 0.5, scale=18, bump_s=0.08)
    m, nt, b = node_mat("monitor_screen")
    tc = nt.nodes.new("ShaderNodeTexCoord"); gr = nt.nodes.new("ShaderNodeTexGradient")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*srgb("#0b1018"), 1); ramp.color_ramp.elements[1].color = (*srgb("#1d2a3c"), 1)
    nt.links.new(tc.outputs["UV"], sep.inputs["Vector"]); nt.links.new(sep.outputs["Y"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 1.0
    b.inputs["Base Color"].default_value = (0, 0, 0, 1); b.inputs["Roughness"].default_value = 0.15
    M["monitor_screen"] = m
    return M

# ---------------------------------------------------------------- lights / world / render

def build_lights():
    L = {}
    def area(name, size, loc, rot, energy, color=(1, 1, 1), shape="RECTANGLE", sy=None):
        d = bpy.data.lights.new(name, "AREA"); d.energy = energy; d.color = color; d.shape = shape
        d.size = size; d.size_y = sy or size
        o = link(bpy.data.objects.new(name, d)); o.location = loc; o.rotation_euler = [math.radians(a) for a in rot]
        L[name] = o; return o
    area("key", 1.2, (-1.1, -0.9, 1.3), (52, 0, -48), 120, (1.0, 0.93, 0.85), sy=0.8)       # soft directional key
    area("fill", 1.5, (1.4, -1.2, 0.6), (75, 0, 50), 15, (0.75, 0.85, 1.0))                  # cool low fill
    area("rim", 0.6, (0.9, 0.9, 0.7), (-60, 0, 140), 60, (0.8, 0.88, 1.0), sy=0.3)          # back rim on product edges
    area("window", 2.0, (-2.2, 0.1, 0.9), (0, -75, 0), 0, (0.6, 0.72, 1.0), sy=1.2)          # moon / morning window, off-screen left
    # reflection card: soft panel seen only in glossy reflections (gives the black glass a believable sheen)
    bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
    card = mesh_obj("refl_card", bm, None); card.scale = (0.9, 0.5, 1)
    m, nt, b = node_mat("refl_card"); b.inputs["Base Color"].default_value = (0, 0, 0, 1)
    b.inputs["Emission Color"].default_value = (1.0, 0.95, 0.9, 1); b.inputs["Emission Strength"].default_value = 1.2
    card.data.materials.append(m)
    card.visible_camera = False; card.visible_diffuse = False; card.visible_shadow = False; card.visible_volume_scatter = False
    L["refl_card"] = card
    sd = bpy.data.lights.new("sun", "SUN"); sd.energy = 0; sd.angle = math.radians(1.5); sd.color = (1.0, 0.78, 0.55)
    so = link(bpy.data.objects.new("sun", sd)); so.rotation_euler = (math.radians(62), 0, math.radians(-78)); L["sun"] = so
    return L


def setup_world():
    w = bpy.data.worlds.new("world"); bpy.context.scene.world = w; w.use_nodes = True
    bg = w.node_tree.nodes["Background"]; bg.inputs["Color"].default_value = (*srgb("#0c0e12"), 1); bg.inputs["Strength"].default_value = 0.25
    return bg


def setup_render(engine="CYCLES", samples=96, res=(1920, 1080), pct=100):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = pct
    sc.render.fps = 30
    sc.render.image_settings.file_format = "PNG"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    if engine == "CYCLES":
        sc.render.engine = "CYCLES"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for dt in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = dt; prefs.get_devices()
                if any(d.type == dt for d in prefs.devices):
                    for d in prefs.devices: d.use = d.type == dt
                    sc.cycles.device = "GPU"; break
            except TypeError:
                continue
        sc.cycles.samples = samples
        sc.cycles.use_denoising = True
        sc.cycles.max_bounces = 6
        sc.cycles.caustics_reflective = sc.cycles.caustics_refractive = False
        sc.cycles.use_adaptive_sampling = True
    else:
        sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
        ee = sc.eevee
        ee.taa_render_samples = samples
        for attr, val in (("use_raytracing", True), ("use_shadows", True), ("use_gtao", True)):
            if hasattr(ee, attr): setattr(ee, attr, val)


def build_all():
    reset()
    M = make_materials()
    prod = build_product(M)
    S = build_desk(M)
    L = build_lights()
    bg = setup_world()
    cam_d = bpy.data.cameras.new("cam"); cam = link(bpy.data.objects.new("cam", cam_d)); bpy.context.scene.camera = cam
    cam_d.sensor_width = 36; cam_d.dof.use_dof = True
    tgt = link(bpy.data.objects.new("cam_target", None))
    tc = cam.constraints.new("TRACK_TO"); tc.target = tgt; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"
    cam_d.dof.focus_object = tgt
    return dict(M=M, product=prod, S=S, L=L, world=bg, cam=cam, target=tgt)
