"""Build the confirmed native Spine character into an uploadable mmap role.

Compile the texture/atlas together, preserve the fitted native skeleton, then
check the resulting payload with the production OTA gate and layout runtime.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess

from PIL import Image
from pack_spine import pack_spine, rewrite_atlas_texture_name, read_spine_binary_version
from prune_spine_upper_body import Parser, write
from prepare_spine_compact_role import BinaryHeader

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build/spine_role_layout/hero_056_s01_no_props_20261003"
DEST = ROOT / "releases/hero_056_s01_160x240_20261003"
WORK = ROOT / "build/spine_role_layout/hero_056_s01_delivery_20261003"
ROLE_ID = "hero_056_s01_clean_512"
VERSION = "20261003.1"


def shrink_atlas(text, factor, target):
    output = []
    for line in text.splitlines():
        if ":" not in line:
            output.append(line)
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if key == "size":
            output.append(f"size:{target[0]},{target[1]}")
        elif key == "scale":
            output.append(f"scale:{float(value) * factor:.10g}")
        elif key in ("bounds", "offsets"):
            values = [int(v) for v in value.split(",")]
            if len(values) != 4:
                raise ValueError("unexpected atlas entry: " + line)
            scaled = [int(v * factor + 0.5) for v in values]
            scaled[2] = max(1, scaled[2])
            scaled[3] = max(1, scaled[3])
            output.append(key + ":" + ",".join(str(v) for v in scaled))
        elif key == "rotate":
            if value not in ("0", "90", "180", "270", "true", "false"):
                raise ValueError("unsupported rotation")
            output.append(line)
        elif key in ("filter", "pma"):
            output.append(line)
        else:
            raise ValueError("unknown atlas property: " + key)
    return rewrite_atlas_texture_name("\n".join(output) + "\n")


def check_atlas(text, target):
    records = []
    current = None
    for line in text.splitlines()[1:]:
        if not line.strip():
            continue
        if ":" not in line:
            current = {"name": line.strip(), "rotate": "0"}
            records.append(current)
        elif current is not None:
            key, value = (part.strip() for part in line.split(":", 1))
            current[key] = value
    for record in records:
        x, y, width, height = map(int, record["bounds"].split(","))
        if record["rotate"] in ("90", "270", "true"):
            width, height = height, width
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > target[0] or y + height > target[1]:
            raise ValueError("out-of-range atlas region: " + record["name"])
    if not records:
        raise ValueError("atlas empty")


def main():
    global DEST, WORK, ROLE_ID, VERSION
    cli = argparse.ArgumentParser()
    cli.add_argument('--large-bottom', action='store_true')
    cli.add_argument('--texture-edge', type=int, choices=[512, 1024])
    cli.add_argument('--keep-large-layout', action='store_true',
                     help='Reuse the delivered 1024 skeleton and scale exactly for a texture-only comparison.')
    options = cli.parse_args()
    if options.keep_large_layout and not options.large_bottom:
        cli.error('--keep-large-layout requires --large-bottom')
    texture_edge = options.texture_edge or (1024 if options.large_bottom else 512)
    target_rect = [40, 38, 240, 280] if options.large_bottom else [80, 40, 160, 240]
    if options.large_bottom:
        DEST = ROOT / f'releases/hero_056_s01_bottom_{texture_edge}_20261003'
        WORK = ROOT / f'build/spine_role_layout/hero_056_s01_bottom_{texture_edge}_delivery_20261003'
        ROLE_ID = f'hero_056_s01_bottom_{texture_edge}'
        VERSION = '20261003.3' if texture_edge == 512 else '20261003.2'
    assets = WORK / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    DEST.mkdir(parents=True, exist_ok=True)
    report = json.loads((SOURCE / "edit-report.json").read_text(encoding="utf-8"))
    scale = report["scale"]
    original = (SOURCE / "assets/skeleton.skel").read_bytes()
    assert original.count(b"\x06wait1") == 1
    raw = original.replace(b"\x06wait1", b"\x0btalk_start", 1)
    parsed = Parser(raw).parse()
    hidden = {'qiu', 'shui'}
    if options.large_bottom:
        hidden.add('ty_1')  # Separate ground shadow is not part of the character.
        keep_slots = {i for i, slot in enumerate(parsed.slots) if slot.name not in hidden}
        keep_bones = set(range(len(parsed.bones)))
        keep_constraints = {kind: set(range(len(records))) for kind, records in parsed.constraints.items()}
        maps = {'bone': {i: i for i in keep_bones},
                'order': {c.order: c.order for records in parsed.constraints.values() for c in records}}
        maps.update({kind: {i: i for i in indices} for kind, indices in keep_constraints.items()})
        raw, _ = write(parsed, keep_slots, keep_bones, keep_constraints, maps)
        parsed = Parser(raw).parse()
    names = [a["name"] for a in parsed.animations]
    assert names == ["idle", "talk_start"]
    assert len(parsed.bones) == report["bones_preserved"]
    assert {k: len(v) for k, v in parsed.constraints.items()} == report["constraints_preserved"]
    removed_slots = {i for i, slot in enumerate(parsed.slots) if slot.name in hidden}
    assert not removed_slots.intersection(slot for slot, _ in parsed.skin)
    reference = None
    reference_skeleton = None
    if options.keep_large_layout:
        reference = ROOT / 'releases/hero_056_s01_bottom_1024_20261003'
        reference_manifest = json.loads((reference / 'manifest.json').read_text(encoding='utf-8'))
        scale = reference_manifest['role']['scale']
        reference_skeleton = (reference / 'assets/skeleton.skel').read_bytes()
        raw = reference_skeleton
        parsed = Parser(raw).parse()
        assert [a['name'] for a in parsed.animations] == names
        assert len(parsed.bones) == report['bones_preserved']
        assert {k: len(v) for k, v in parsed.constraints.items()} == report['constraints_preserved']
        assert not removed_slots.intersection(slot for slot, _ in parsed.skin)
    (assets / "skeleton.skel").write_bytes(raw)
    text = (SOURCE / "assets/skeleton.atlas").read_text(encoding="utf-8")
    with Image.open(SOURCE / "assets/texture.png") as source:
        original_size = source.size
        factor = texture_edge / max(original_size)
        target = tuple(round(v * factor) for v in original_size)
        rgba = source.convert("RGBA")
        # The atlas is pma:true. Resample associated channels independently;
        # preserve this encoding instead of premultiplying it a second time.
        assert re.search(r"(?m)^pma:true$", text)
        scaled = Image.merge("RGBA", tuple(band.resize(target, Image.Resampling.LANCZOS) for band in rgba.split()))
        scaled.save(assets / "texture.png", optimize=True)
    atlas = shrink_atlas(text, factor, target)
    check_atlas(atlas, target)
    (assets / "skeleton.atlas").write_text(atlas, encoding="utf-8", newline="\n")
    env = os.environ.copy()
    env["PATH"] = str(ROOT / "build/host_mingw/llvm-mingw-20250613-ucrt-x86_64/bin") + os.pathsep + env.get("PATH", "")
    layout = ROOT / "build/spine_role_layout/spine_role_layout.exe"
    preflight = ROOT / "build/spine_role_layout/spine_role_package_check.exe"
    if options.large_bottom and not options.keep_large_layout:
        # Fit the native animated geometry, not the PNG canvas. Root translation
        # uses the same node (160,0) and Y inversion as the device player.
        subprocess.run([str(layout), 'scan', str(assets), '1', str(WORK / 'unit-bounds.json'), 'overlay-idle'], env=env, check=True)
        unit = json.loads((WORK / 'unit-bounds.json').read_text())
        ux1, uy1, ux2, uy2 = unit['bounds']
        scale = min(240 / (ux2 - ux1), 280 / (uy2 - uy1)) * 0.98
        fitted = bytearray(raw)
        root = BinaryHeader(fitted).root()
        struct.pack_into('>f', fitted, root['x_offset'], root['x'] - (ux1 + ux2) / 2)
        struct.pack_into('>f', fitted, root['y_offset'], root['y'] + 2 / scale - uy1)
        raw = bytes(fitted)
        parsed = Parser(raw).parse()
        (assets / 'skeleton.skel').write_bytes(raw)
    result = subprocess.run([str(preflight), str(assets / "skeleton.skel"), str(assets / "skeleton.atlas"), "default"],
                            env=env, capture_output=True, text=True, check=True)
    (DEST / "preflight.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    subprocess.run([str(layout), "scan", str(assets), str(scale), str(WORK / "bounds.json"), "overlay-idle"], env=env, check=True)
    bounds = json.loads((WORK / "bounds.json").read_text())
    x1, y1, x2, y2 = bounds["bounds"]
    screen_bounds = [x1 + 160, 320 - y2, x2 + 160, 320 - y1]
    if options.large_bottom:
        assert 39 <= screen_bounds[0] < screen_bounds[2] <= 281, screen_bounds
        assert 37 <= screen_bounds[1] < screen_bounds[3] <= 320, screen_bounds
        assert 317 <= screen_bounds[3] <= 320, screen_bounds
    else:
        assert 80 <= screen_bounds[0] < screen_bounds[2] <= 240
        assert 40 <= screen_bounds[1] < screen_bounds[3] <= 280
    assert not hidden.intersection(bounds["attachments"])
    assert "default" in bounds["skins"]
    # Draw the final native assets, including the idle + speaking track combination.
    with Image.open(assets / "texture.png") as texture:
        rgba = texture.convert("RGBA").tobytes()
    native = bytearray(len(rgba))
    native[0::4], native[1::4], native[2::4], native[3::4] = rgba[3::4], rgba[2::4], rgba[1::4], rgba[0::4]
    rgba_path = WORK / "native_texture.rgba"
    rgba_path.write_bytes(native)
    visible_bounds = None
    for alignment_pass in range(2 if options.large_bottom and not options.keep_large_layout else 1):
        visible_records = []
        for motion in names:
            subprocess.run([str(layout), "preview", str(assets), str(scale), str(rgba_path), str(WORK / motion),
                            motion, "bilinear", "overlay-idle"], env=env, check=True)
            visible_records.append(json.loads((WORK / motion / 'visible-bounds.json').read_text())['bounds'])
            frame = WORK / motion / (motion + "_3.rgb565")
            pixels = struct.unpack("<102400H", frame.read_bytes())
            rgb = bytes(c for v in pixels for c in ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
            Image.frombytes("RGB", (320, 320), rgb).save(DEST / (motion + "_preview.png"))
        visible_bounds = [min(v[0] for v in visible_records), min(v[1] for v in visible_records),
                          max(v[2] for v in visible_records), max(v[3] for v in visible_records)]
        if options.large_bottom and not options.keep_large_layout and alignment_pass == 0:
            # Transparent attachment padding must not create a visible gap.
            # The first preview is unclipped. Move its actual lowest pixel to 318.
            assert visible_bounds[3] < 319
            shift_pixels = 318 - visible_bounds[3]
            fitted = bytearray(raw)
            root = BinaryHeader(fitted).root()
            struct.pack_into('>f', fitted, root['y_offset'], root['y'] - shift_pixels / scale)
            raw = bytes(fitted)
            parsed = Parser(raw).parse()
            (assets / 'skeleton.skel').write_bytes(raw)
    if options.large_bottom:
        assert 317 <= visible_bounds[3] <= 319, visible_bounds
        subprocess.run([str(layout), 'scan', str(assets), str(scale), str(WORK / 'bounds.json'), 'overlay-idle'], env=env, check=True)
        bounds = json.loads((WORK / 'bounds.json').read_text())
        x1, y1, x2, y2 = bounds['bounds']
        screen_bounds = [x1 + 160, 320 - y2, x2 + 160, 320 - y1]
    size = pack_spine(assets, DEST / "spine.bin", ROLE_ID, VERSION, "default", scale, "4.2")
    data = (DEST / "spine.bin").read_bytes()
    count, checksum, length = struct.unpack_from("<III", data)
    assert count == 4 and length == len(data) - 12 and sum(data[12:]) & 65535 == checksum
    entries = {}
    spans = []
    base = 12 + 44 * count
    for index in range(count):
        start = 12 + index * 44
        name = data[start:start + 32].split(b"\0", 1)[0].decode("utf-8")
        payload_size, offset, width, height = struct.unpack_from("<IIHH", data, start + 32)
        a, b = base + offset, base + offset + 2 + payload_size
        assert name not in entries and b <= len(data) and data[a:a + 2] == b"\x5a\x5a"
        assert width == height == 0
        entries[name] = data[a + 2:b]
        spans.append((a, b))
    assert set(entries) == {"role.json", "skeleton.skel", "skeleton.atlas", "texture.png"}
    spans.sort()
    assert spans[0][0] == base and spans[-1][1] == len(data)
    assert all(left[1] == right[0] for left, right in zip(spans, spans[1:]))
    role = json.loads(entries["role.json"])
    assert role["format"] == 2 and role["skin"] == "default" and role["role_id"] == ROLE_ID and role["version"] == VERSION
    assert role["spine_runtime_version"] == "4.2" and abs(role["scale"] - scale) < 1e-10
    for name in ("skeleton.skel", "skeleton.atlas", "texture.png"):
        assert entries[name] == (assets / name).read_bytes(), name
    if reference_skeleton is not None:
        assert entries['skeleton.skel'] == reference_skeleton
        assert scale == reference_manifest['role']['scale']
    final_assets = DEST / "assets"
    final_assets.mkdir(exist_ok=True)
    for name, payload in entries.items():
        (final_assets / name).write_bytes(payload)
    # Run the exact device gate on the bytes extracted from the actual binary.
    result = subprocess.run([str(preflight), str(final_assets / "skeleton.skel"), str(final_assets / "skeleton.atlas"), role["skin"]],
                            env=env, capture_output=True, text=True, check=True)
    (DEST / "preflight.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    digest = hashlib.sha256(data).hexdigest()
    manifest = dict(role=role, bytes=size, sha256=digest, animations=names,
                    runtime=read_spine_binary_version(entries["skeleton.skel"]),
                    bones=len(parsed.bones), constraints={k: len(v) for k, v in parsed.constraints.items()},
                    source_texture=original_size, texture=target, texture_decode_rgba_bytes=target[0] * target[1] * 4,
                    texture_and_atlas_scale=factor, screen=[320, 320], target_rect=target_rect,
                    alignment='bottom_center' if options.large_bottom else 'center',
                    sampled_screen_bounds=screen_bounds, sampled_envelope=[x2 - x1, y2 - y1],
                    native_render_visible_bounds=visible_bounds, native_render_sampling='30 Hz, 14 seconds per action including speaking overlay',
                    sampled_idle_and_speaking_overlay=True, removed_attachments=sorted(hidden),
                    mmap_file_table_and_checksum_verified=True, embedded_assets_verified=True,
                    production_ota_preflight="ok", firmware_changed=False,
                    layout_reference=str(reference) if reference else None,
                    skeleton_and_scale_identical_to_reference=reference_skeleton is not None,
                    device_fps_verified=False, uploaded=False)
    (DEST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DEST / "SHA256SUMS.txt").write_text(digest + "  spine.bin\n", encoding="ascii")
    shutil.copyfile(WORK / "bounds.json", DEST / "bounds.json")
    (DEST / "README.md").write_text(
        f"""# 056去道具角色包

上传文件：本目录的 spine.bin。显示名建议：056放大贴底{texture_edge}版（若使用大图贴底选项）。
这是视觉角色资源包，mmap格式，非ZIP、非应用固件。你自行在视觉角色页面发布并下载到设备。

- 保留原人物、姿势与动画；去掉球、整组饮料、毛巾和地上的花。
- 大图贴底选项另外去掉独立地面阴影ty_1，以人物自身范围对齐屏幕底部。
- 最终可见像素范围为{visible_bounds}，底部按可见像素对齐；附件透明边缘的几何坐标可能超出屏幕，渲染器正常裁剪。
- idle为待机循环（原wait）；talk_start为原wait1，当前固件在讲话时调用并循环。
- 皮肤default，Spine导出版本4.2.26，角色格式2，运行库要求4.2。
- 在320×320屏幕的{target_rect[2]}×{target_rect[3]}范围内等比例显示；布局为{manifest['alignment']}，不拉伸人物。实际动作包围范围为{(x2-x1):.2f}×{(y2-y1):.2f}像素。
- 贴图从2048×512等比缩到{target[0]}×{target[1]}，图集坐标、偏移、原始尺寸和scale同步缩放。
- {target[0]}×{target[1]}保留本角色原图集比例。解码RGBA约{target[0]*target[1]*4//1024} KiB。
- 大图布局对照来源：{reference}；骨骼文件和加载比例与该来源完全一致：{reference_skeleton is not None}。使用keep-large-layout时只改变纹理、配套图集和角色包标识。
- 骨骼{len(parsed.bones)}根、物理约束{len(parsed.constraints['physics'])}个，本次没有做骨骼/约束精简；不保证真机8 FPS。
- 骨骼动作在多种步进频率与三个周期采样，并覆盖idle与talk_start叠加布局；这不能替代真机长期验证。
- idle_preview.png与talk_start_preview.png使用最终缩小贴图与生产渲染路径生成，预览底色不随角色包更改设备壁纸。
- 原始素材和此前预览保持不变；未上传、未烧录、未修改固件。

角色ID：{ROLE_ID}
版本：{VERSION}
加载比例：{scale}
文件大小：{size}字节（{size/1024:.2f} KiB），小于4 MiB角色分区限制。
SHA256：{digest}

已检查四个内嵌文件、文件名、长度、文件表、0x5A5A前缀、校验和、PNG尺寸与图集边界；
对最终bin中提取出的模型运行设备OTA使用的同一预检，结果见preflight.txt。
""", encoding="utf-8")
    print(json.dumps({"path": str(DEST / "spine.bin"), **manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
