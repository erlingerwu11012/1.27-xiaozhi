"""Edit native Spine attachments and render a centered 160x240 layout preview.

No raster retouching, source texture changes, firmware changes or OTA packaging.
"""
from pathlib import Path
import json
import os
import shutil
import struct
import subprocess

from prune_spine_upper_body import Parser, write
from prepare_spine_compact_role import BinaryHeader

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("F:/BaiduNetdiskDownload/都市少女spine动画 141角色+46背景/都市少女spine动画 141角色+46背景/立绘/hero_056_s01")
OUT = ROOT / "build/spine_role_layout/hero_056_s01_no_props_20261003"


def main():
    assets = OUT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    original = (SOURCE / "hero_056_s01.skel").read_bytes()
    parsed = Parser(original).parse()
    hidden = {"qiu", "shui"}
    assert hidden.issubset({slot.name for slot in parsed.slots})
    slots = {i for i, slot in enumerate(parsed.slots) if slot.name not in hidden}
    bones = set(range(len(parsed.bones)))
    selected = {kind: set(range(len(records))) for kind, records in parsed.constraints.items()}
    maps = {
        "bone": {i: i for i in bones},
        "order": {c.order: c.order for records in parsed.constraints.values() for c in records},
    }
    for kind, indices in selected.items():
        maps[kind] = {i: i for i in indices}
    raw, timeline_changes = write(parsed, slots, bones, selected, maps)
    assert raw.count(b"\x05wait") == 1
    raw = raw.replace(b"\x05wait", b"\x05idle", 1)
    rewritten = Parser(raw).parse()
    assert len(rewritten.bones) == len(parsed.bones)
    assert {k: len(v) for k, v in rewritten.constraints.items()} == {k: len(v) for k, v in parsed.constraints.items()}
    (assets / "skeleton.skel").write_bytes(raw)
    atlas = (SOURCE / "hero_056_s01.atlas").read_text(encoding="utf-8")
    (assets / "skeleton.atlas").write_text(atlas.replace("hero_056_s01.png", "texture.png", 1), encoding="utf-8")
    shutil.copyfile(SOURCE / "hero_056_s01.png", assets / "texture.png")
    exe = ROOT / "build/spine_role_layout/spine_role_layout.exe"
    env = os.environ.copy()
    env["PATH"] = str(ROOT / "build/host_mingw/llvm-mingw-20250613-ucrt-x86_64/bin") + os.pathsep + env.get("PATH", "")
    subprocess.run([str(exe), "scan", str(assets), "1", str(OUT / "unscaled-bounds.json")], env=env, check=True)
    scan = json.loads((OUT / "unscaled-bounds.json").read_text())
    assert not hidden.intersection(scan["attachments"])
    x1, y1, x2, y2 = scan["bounds"]
    scale = min(160 / (x2 - x1), 240 / (y2 - y1)) * 0.98
    dx = -(x1 + x2) / 2
    dy = 160 / scale - (y1 + y2) / 2
    fitted = bytearray(raw)
    root = BinaryHeader(fitted).root()
    struct.pack_into(">f", fitted, root["x_offset"], root["x"] + dx)
    struct.pack_into(">f", fitted, root["y_offset"], root["y"] + dy)
    Parser(fitted).parse()
    (assets / "skeleton.skel").write_bytes(fitted)
    subprocess.run([str(exe), "scan", str(assets), str(scale), str(OUT / "fitted-bounds.json")], env=env, check=True)
    fitted_scan = json.loads((OUT / "fitted-bounds.json").read_text())
    fx1, fy1, fx2, fy2 = fitted_scan["bounds"]
    expected = [fx1 + 160, 320 - fy2, fx2 + 160, 320 - fy1]
    assert 80 <= expected[0] < expected[2] <= 240
    assert 40 <= expected[1] < expected[3] <= 280
    role = dict(atlas="skeleton.atlas", skel="skeleton.skel", png="texture.png", skin="default",
                format=2, scale=scale, spine_runtime_version="4.2",
                role_id="hero_056_s01_no_props", version="20261003.preview")
    (assets / "role.json").write_text(json.dumps(role, ensure_ascii=False), encoding="utf-8")
    # Decode the unchanged atlas for the native renderer; do not resize or retouch it.
    from PIL import Image
    with Image.open(assets / "texture.png") as texture:
        rgba = texture.convert("RGBA").tobytes()
        texture_size = texture.size
    rgba_path = OUT / "native_texture.rgba"
    # The engine reads packed RRGGBBAA uint32 values on a little-endian host.
    native = bytearray(len(rgba))
    native[0::4] = rgba[3::4]
    native[1::4] = rgba[2::4]
    native[2::4] = rgba[1::4]
    native[3::4] = rgba[0::4]
    rgba_path.write_bytes(native)
    for motion in ("idle", "wait1"):
        subprocess.run([str(exe), "preview", str(assets), str(scale), str(rgba_path),
                        str(OUT / motion), motion, "bilinear"], env=env, check=True)
    # Encode native RGB565 framebuffer outputs as PNG previews.
    for framebuffer in OUT.glob("*/*.rgb565"):
        pixels = struct.unpack("<102400H", framebuffer.read_bytes())
        rgb = bytes(c for v in pixels for c in ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
        Image.frombytes("RGB", (320, 320), rgb).save(framebuffer.with_suffix(".png"))
    report = dict(source=str(SOURCE), hidden_slots=sorted(hidden), bones_preserved=len(parsed.bones),
                  constraints_preserved={k: len(v) for k, v in parsed.constraints.items()},
                  animations=[a["name"] for a in rewritten.animations], timeline_changes=timeline_changes,
                  original_texture_unchanged=True, texture_size=texture_size, screen=[320, 320],
                  safe_area=[80, 40, 160, 240], scale=scale, expected_screen_bounds=expected,
                  actual_envelope=[fx2 - fx1, fy2 - fy1], bundle_created=False, firmware_changed=False)
    (OUT / "edit-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    release = ROOT / "releases/hero_056_s01_preview_160x240_20261003"
    release.mkdir(parents=True, exist_ok=True)
    for name, source in (("idle_preview.png", OUT / "idle/idle_0.png"),
                         ("idle_motion_preview.png", OUT / "idle/idle_3.png"),
                         ("second_motion_preview.png", OUT / "wait1/wait1_3.png"),
                         ("edit-report.json", OUT / "edit-report.json")):
        shutil.copyfile(source, release / name)
    (release / "README.txt").write_text(
        "Native Spine preview only; no OTA binary created.\nRemoved qiu and shui skin attachments and their animation timelines; retained original character bones and constraints.\n"
        "The shui attachment includes all drinks, towel and ground flower. Original PNG atlas is unchanged.\n"
        "Character retains original kneeling pose, uniformly fitted within the centered 160x240 area of a 320x320 framebuffer.\n"
        "Preserved idle (original wait) and wait1 motions; native renderer uses bilinear sampling.\n"
        "Final compressed atlas and real-device quality/FPS have not been prepared or measured.\n", encoding="utf-8")
    print(json.dumps({"preview": str(release / "idle_preview.png"), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
