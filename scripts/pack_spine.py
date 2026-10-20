#!/usr/bin/env python3
"""Pack an official Spine visual role into generated_spine.bin (mmap assets format)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_default_assets import pack_assets_simple  # noqa: E402

MAX_SPINE_BYTES = 4 * 1024 * 1024  # single dynamic "spine" partition
ROLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
REQUIRED_PACK_NAMES = ("role.json", "skeleton.skel", "skeleton.atlas", "texture.png")
REQUIRED_SPINE_RUNTIME = "4.2"


def read_spine_binary_version(skel_bytes: bytes) -> str:
    """Read the version string from a Spine 4.x binary skeleton header."""
    if len(skel_bytes) < 8:
        die("skeleton.skel too small to contain a Spine 4.x header")
    pos = 8  # lowHash(int) + highHash(int)
    length = 0
    shift = 0
    while True:
        if pos >= len(skel_bytes):
            die("skeleton.skel: truncated version varint")
        b = skel_bytes[pos]
        pos += 1
        length |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
        if shift > 28:
            die("skeleton.skel: malformed version varint")
    if length <= 0 or pos + (length - 1) > len(skel_bytes):
        die("skeleton.skel: truncated version string")
    return skel_bytes[pos : pos + (length - 1)].decode("ascii", "replace")


def is_spine_42(version: str) -> bool:
    return len(version) >= 3 and version[:3] == "4.2" and (
        len(version) == 3 or version[3] == "."
    )


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def detect_source_files(source_dir: Path) -> tuple[Path, Path, Path]:
    skel = source_dir / "skeleton.skel"
    atlas = source_dir / "skeleton.atlas"
    png = source_dir / "texture.png"
    if skel.is_file() and atlas.is_file() and png.is_file():
        return skel, atlas, png

    skels = sorted(source_dir.glob("*.skel"))
    atlases = sorted(source_dir.glob("*.atlas"))
    pngs = sorted(p for p in source_dir.glob("*.png") if p.name != "room.png")
    if len(skels) != 1 or len(atlases) != 1 or len(pngs) != 1:
        die(
            "source dir must contain either skeleton.{skel,atlas}+texture.png "
            "or exactly one .skel, one .atlas, and one non-room .png"
        )
    return skels[0], atlases[0], pngs[0]


def rewrite_atlas_texture_name(atlas_text: str, texture_name: str = "texture.png") -> str:
    lines = atlas_text.splitlines(keepends=True)
    if not lines:
        die("atlas file is empty")
    # Spine atlas: optional blank first line, then texture filename
    idx = 0
    if lines[0].strip() == "" and len(lines) > 1:
        idx = 1
    lines[idx] = texture_name + ("\n" if not lines[idx].endswith("\n") else "")
    if not lines[idx].endswith("\n"):
        lines[idx] += "\n"
    # Normalize first content line to texture.png regardless of previous name
    lines[idx] = texture_name + "\n"
    return "".join(lines)


def validate_role_id(role_id: str) -> None:
    if not role_id or not ROLE_ID_RE.fullmatch(role_id):
        die(f"illegal role_id: {role_id!r} (allowed: [A-Za-z0-9_-]+)")


def pack_spine(
    source_dir: Path,
    output: Path,
    role_id: str,
    version: str,
    skin: str,
    scale: float,
    spine_runtime_version: str,
) -> int:
    validate_role_id(role_id)
    if scale <= 0 or scale > 10:
        die(f"scale must be a reasonable positive number, got {scale}")
    for name in (role_id, version, skin):
        if len(name) > 31:
            die(f"name too long (>31): {name}")

    if not source_dir.is_dir():
        die(f"source dir not found: {source_dir}")

    skel_src, atlas_src, png_src = detect_source_files(source_dir)

    skel_bytes = skel_src.read_bytes()
    real_runtime = read_spine_binary_version(skel_bytes)
    print(f"skeleton runtime version: {real_runtime}")
    if not is_spine_42(real_runtime):
        die(
            f"skeleton runtime version {real_runtime!r} is not a Spine 4.2 export; "
            f"refusing to pack"
        )
    if spine_runtime_version != REQUIRED_SPINE_RUNTIME:
        die(
            f"--spine-runtime-version must be {REQUIRED_SPINE_RUNTIME!r}, "
            f"got {spine_runtime_version!r}"
        )

    with tempfile.TemporaryDirectory(prefix="spine_pack_") as tmp:
        staging = Path(tmp) / "assets"
        staging.mkdir()

        role = {
            "format": 2,
            "role_id": role_id,
            "version": version,
            "spine_runtime_version": REQUIRED_SPINE_RUNTIME,
            "skel": "skeleton.skel",
            "atlas": "skeleton.atlas",
            "png": "texture.png",
            "skin": skin,
            "scale": float(scale),
        }
        # Deterministic JSON
        role_bytes = (json.dumps(role, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode(
            "utf-8"
        )
        (staging / "role.json").write_bytes(role_bytes)
        shutil.copy2(skel_src, staging / "skeleton.skel")
        atlas_text = atlas_src.read_text(encoding="utf-8", errors="replace")
        (staging / "skeleton.atlas").write_text(
            rewrite_atlas_texture_name(atlas_text), encoding="utf-8", newline="\n"
        )
        shutil.copy2(png_src, staging / "texture.png")

        present = sorted(p.name for p in staging.iterdir() if p.is_file())
        if tuple(present) != tuple(sorted(REQUIRED_PACK_NAMES)):
            die(f"unexpected staging files: {present}, expected {sorted(REQUIRED_PACK_NAMES)}")

        for name in REQUIRED_PACK_NAMES:
            if len(name) > 31:
                die(f"packed filename too long: {name}")

        include_dir = Path(tmp) / "include"
        include_dir.mkdir()
        out_tmp = Path(tmp) / "spine.bin"
        pack_assets_simple(str(staging), str(include_dir), str(out_tmp), "spine", 32)

        size = out_tmp.stat().st_size
        print(f"Spine package size: {size} bytes ({size / 1024:.2f} KiB)")
        if size > MAX_SPINE_BYTES:
            die(f"package exceeds {MAX_SPINE_BYTES} bytes (got {size})")
        if size <= 0:
            die("empty package")

        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_tmp, output)
        print(f"Wrote {output}")
        print(f"Contents: {', '.join(REQUIRED_PACK_NAMES)}")
        print(f"role_id={role_id} version={version} skin={skin} scale={scale} "
              f"spine_runtime_version={spine_runtime_version}")
        return size


def list_bundle_files(path: Path) -> list[tuple[str, int]]:
    data = path.read_bytes()
    if len(data) < 12:
        die("bundle too small")
    import struct

    files, _chk, slen = struct.unpack_from("<III", data, 0)
    if 12 + files * 44 > len(data):
        die("invalid file table")
    out = []
    off = 12
    for _ in range(files):
        name = data[off : off + 32].split(b"\x00", 1)[0].decode("utf-8", "replace")
        size, _aoff, _w, _h = struct.unpack_from("<IIHH", data, off + 32)
        out.append((name, size))
        off += 44
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack Spine role into mmap bundle")
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--role-id", default="c131_00")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--skin", default="00")
    parser.add_argument("--scale", type=float, default=0.155)
    parser.add_argument(
        "--spine-runtime-version",
        default=REQUIRED_SPINE_RUNTIME,
        help="Required Spine runtime major.minor; the real skeleton header must match",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="After packing (or on existing --output), verify required files and size",
    )
    args = parser.parse_args()

    if args.check and args.output.is_file() and not args.source_dir:
        pass

    size = pack_spine(
        args.source_dir.resolve(),
        args.output.resolve(),
        args.role_id,
        args.version,
        args.skin,
        args.scale,
        args.spine_runtime_version,
    )

    if args.check or True:
        names = {n for n, _ in list_bundle_files(args.output.resolve())}
        missing = [n for n in REQUIRED_PACK_NAMES if n not in names]
        if missing:
            die(f"bundle missing files: {missing}")
        unexpected = names - set(REQUIRED_PACK_NAMES)
        if unexpected:
            die(f"bundle has unexpected files: {sorted(unexpected)}")
        if size > MAX_SPINE_BYTES:
            die("size check failed")
        print("CHECK OK")


if __name__ == "__main__":
    main()
