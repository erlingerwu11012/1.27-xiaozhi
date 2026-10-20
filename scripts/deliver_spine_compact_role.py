"""Verify the mmap role bundle and copy the compact role delivery outside build."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import struct
from pack_spine import rewrite_atlas_texture_name

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build/spine_role_layout/hero_001_compact_20261002"
DEST = ROOT / "releases/hero_001_compact_20261002"

def main():
    data = (SOURCE / "spine.bin").read_bytes()
    count, checksum, combined_size = struct.unpack_from("<III", data)
    if count != 4 or combined_size != len(data)-12 or (sum(data[12:]) & 65535) != checksum:
        raise ValueError("mmap bundle size/checksum mismatch")
    entries = {}
    start = 12+44*count
    for i in range(count):
        p = 12+44*i
        name = data[p:p+32].split(b"\0",1)[0].decode("utf-8")
        size, offset, width, height = struct.unpack_from("<IIHH",data,p+32)
        if name in entries or start+offset+2+size > len(data): raise ValueError("invalid file entry")
        if data[start+offset:start+offset+2] != b"\x5a\x5a": raise ValueError("invalid entry prefix")
        entries[name] = data[start+offset+2:start+offset+2+size]
    if set(entries) != {"role.json","skeleton.skel","skeleton.atlas","texture.png"}:
        raise ValueError("unexpected file set")
    role = json.loads(entries["role.json"])
    layout = json.loads((SOURCE/"layout.json").read_text(encoding="utf-8"))
    region = json.loads((SOURCE/"render_regions.json").read_text(encoding="utf-8"))
    scan = json.loads((SOURCE/"scaled_bounds.json").read_text(encoding="utf-8"))
    names = [motion["name"] for motion in scan["animations"]]
    if "idle" not in names or role["skin"] not in scan["skins"]: raise ValueError("required idle/skin absent")
    if abs(role["scale"]-scan["scale"]) > 1e-8: raise ValueError("scale mismatch")
    for name in ("skeleton.skel","skeleton.atlas","texture.png"):
        expected = (SOURCE/"assets"/name).read_bytes()
        if name=="skeleton.atlas": expected=rewrite_atlas_texture_name(expected.decode("utf-8").replace("\r\n","\n")).encode("utf-8")
        if entries[name] != expected: raise ValueError("embedded asset mismatch: "+name)
    original_dir = Path(layout["source"])
    for name in ("skeleton.atlas","texture.png"):
        expected = (original_dir/name).read_bytes()
        if name=="skeleton.atlas": expected=rewrite_atlas_texture_name(expected.decode("utf-8").replace("\r\n","\n")).encode("utf-8")
        if entries[name] != expected: raise ValueError("atlas/texture unexpectedly changed")
    old = (original_dir/"skeleton.skel").read_bytes()
    new = entries["skeleton.skel"]
    permitted = set(range(layout["root_before"]["x_offset"],layout["root_before"]["y_offset"]+4))
    permitted.update(range(layout["rename_wait_offset"],layout["rename_wait_offset"]+4))
    if len(old)!=len(new) or any(a!=b and i not in permitted for i,(a,b) in enumerate(zip(old,new))):
        raise ValueError("unexpected skeleton edit")
    DEST.mkdir(parents=True,exist_ok=True)
    (DEST/"spine.bin").write_bytes(data)
    assets = DEST/"assets";assets.mkdir(exist_ok=True)
    for name,content in entries.items(): (assets/name).write_bytes(content)
    for name in ("layout.json","scaled_bounds.json","render_regions.json"):
        shutil.copyfile(SOURCE/name,DEST/name)
    for folder,motion in (("preview_idle","idle"),("preview_wait1","wait1")):
        shutil.copyfile(SOURCE/folder/(motion+"_0.png"),DEST/(motion+"_preview.png"))
    # Include a second motion pose with different ribbons/flames for review.
    shutil.copyfile(SOURCE/"preview_wait1/wait1_3.png",DEST/"wait1_preview.png")
    digest = hashlib.sha256(data).hexdigest()
    (DEST/"SHA256SUMS.txt").write_text(digest+"  spine.bin\n",encoding="ascii")
    manifest = dict(role=role,bytes=len(data),sha256=digest,animations=names,
                    skeleton_runtime=scan["runtime"],bones=scan["bones"],physics_constraints=scan["physics"],
                    texture=[512,512],display=[320,320],firmware_node_position=[160,0],
                    changes=["role load scale","root setup translation","wait renamed idle"],
                    rendering_preview=region,compatibility="Spine 4.2 / current 4.30 Home layout",
                    mmap_checksum_verified=True,embedded_assets_verified=True,
                    device_flashing_performed=False,device_fps_verified=False,
                    reference_scale_bounds=layout["expected_screen_bounds"])
    (DEST/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    readme = f"""# 001完整显示、缩小角色包（2026-10-02）

## 上传文件

选择本目录的 `spine.bin`，上传到“视觉角色 → 发布官方角色包”。
显示名建议：`001完整缩小版`。发布后将该角色下载到设备。
这是角色资源包，不是固件；不需要重新烧录固件。

## 调整内容

- 复用之前已缩成512×512的贴图与对应图集，本次没有再缩小。图集坐标保留，贴图名称规范为texture.png。
- 整个骨骼、网格及附件使用同一加载比例：{role['scale']:.12f}。
- 校正根骨骼初始位置，适配现有固件固定原点(160,0)，完整显示头部与脚部。
- 人物、武器、碎石、火焰、飘带及动作速度保留。
- `wait` 改名为 `idle`；另一个动作仍为 `wait1`。
- 原始角色文件保持原样。角色包格式与上传接口保持兼容。

## 显示范围与依据

Spine运行库4.2.26读取两个动作，每个动作按5/10/24/30/60/240 Hz推进三个周期；
240 Hz采样额外包含关键帧时刻。按全附件几何范围计算固定比例，并保留4%余量。
采样涉及327根骨骼、132个物理约束。这是离线布局测量，不能代替设备长时间运行验证。

角色动作采样包围范围约216×192像素，屏幕边界内保留空白。
包含碎石和特效后的整体比例较宽，人物自身仍保持原比例，未拉伸成方形。
预览由当前生产SpineNode及Renderer生成，按320×320屏幕、节点(160,0)、
现有滤波和绘制顺序输出；每个动作推进一个完整周期。
`idle`最大刷新矩形为35,712像素（34.88%），`wait1`为39,220像素（38.30%）。
这些数值只包含角色。首次显示、壁纸更换、字幕及其他UI更新、异常恢复可能扩大区域或全屏提交。
角色包可以减小角色自身刷新范围，不能保证整个UI永远不发生全屏刷新。

`idle_preview.png` / `wait1_preview.png`是320×320原尺寸预览，背景为预览底色。
设备仍使用原壁纸。上传后的显示和实际帧率以真机照片、日志为准。
后续日志重点看 `[RENDER2] original_pixels / sent_pixels` 与实际 `display_fps`。
骨骼、物理约束和动作计算复杂度保留，不能保证帧率按面积缩小比例提升。

## 文件校验

- 大小：{len(data):,}字节（{len(data)/1024:.2f} KiB）
- 角色ID：`{role['role_id']}`
- 版本：`{role['version']}`
- SHA256：`{digest}`
- 包含：role.json、skeleton.skel、skeleton.atlas、texture.png
- mmap文件表、前缀、长度、校验和及内嵌资源已核对。

若要回退，重新选择之前的001角色包下载即可。
"""
    (DEST/"README.md").write_text(readme,encoding="utf-8")
    print(json.dumps(dict(path=str(DEST/"spine.bin"),bytes=len(data),sha256=digest,animations=names),indent=2))

if __name__=="__main__": main()
