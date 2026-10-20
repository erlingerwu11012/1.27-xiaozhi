#!/usr/bin/env python3
"""Pack a signed-OTA-ready wallpaper bundle for the single wallpaper slot."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_default_assets import pack_assets_simple  # noqa: E402

MAX_WALLPAPER_BYTES = 2 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,31}$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_image_spec(spec: str, source_dir: Path) -> tuple[str, Path]:
    if "=" not in spec:
        die(f"--image must be id=file, got {spec!r}")
    image_id, filename = spec.split("=", 1)
    path = (source_dir / filename).resolve()
    if not ID_RE.fullmatch(image_id):
        die(f"invalid wallpaper id: {image_id!r}")
    if not path.is_file() or path.parent != source_dir.resolve():
        die(f"image must be a direct file in --source-dir: {filename!r}")
    return image_id, path


def collect_images(source_dir: Path, specs: list[str]) -> list[tuple[str, Path]]:
    if specs:
        items = [parse_image_spec(spec, source_dir) for spec in specs]
    else:
        items = []
        for path in sorted(source_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                image_id = path.stem
                if not ID_RE.fullmatch(image_id):
                    die(f"filename stem is not a valid wallpaper id: {path.name!r}")
                items.append((image_id, path))
    if not items:
        die("no wallpapers found; add image files or pass --image id=file")
    ids = [item[0] for item in items]
    names = [item[1].name for item in items]
    if len(set(ids)) != len(ids) or len(set(names)) != len(names):
        die("duplicate wallpaper id or image filename")
    if len(items) > 16:
        die("a wallpaper package supports at most 16 images")
    for name in names:
        if len(name.encode("utf-8")) > 31:
            die(f"image filename is too long for mmap bundle: {name!r}")
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--pack-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--default-id", required=True)
    parser.add_argument("--image", action="append", default=[],
                        help="Repeat as wallpaper_id=filename. Default: all direct png/jpg/jpeg files.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    if not source_dir.is_dir():
        die(f"source directory not found: {source_dir}")
    if not ID_RE.fullmatch(args.pack_id) or len(args.pack_id) > 64:
        die(f"invalid pack id: {args.pack_id!r}")
    if not args.version or len(args.version) > 31:
        die("version must be 1..31 characters")
    items = collect_images(source_dir, args.image)
    if args.default_id not in {item[0] for item in items}:
        die("--default-id must name one of the packaged images")

    with tempfile.TemporaryDirectory(prefix="wallpaper_pack_") as tmp:
        root = Path(tmp)
        staging = root / "assets"
        include = root / "include"
        staging.mkdir()
        include.mkdir()
        manifest = {
            "format": 1,
            "pack_id": args.pack_id,
            "version": args.version,
            "default_id": args.default_id,
            "items": [{"id": image_id, "file": path.name} for image_id, path in items],
        }
        (staging / "wallpaper.json").write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        for _, path in items:
            shutil.copy2(path, staging / path.name)
        output_tmp = root / "wallpaper.bin"
        pack_assets_simple(str(staging), str(include), str(output_tmp), "wallpaper", 32)
        size = output_tmp.stat().st_size
        if size <= 0 or size > MAX_WALLPAPER_BYTES:
            die(f"package must be 1..{MAX_WALLPAPER_BYTES} bytes, got {size}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_tmp, args.output)
        print(f"Wrote {args.output} ({size} bytes) with {len(items)} wallpaper(s)")


if __name__ == "__main__":
    main()
