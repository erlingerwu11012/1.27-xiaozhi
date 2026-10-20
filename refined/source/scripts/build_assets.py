"""Build the raster assets used by the page layouts.

Composites the original screen artwork onto the blank product plates using a
perspective warp, and prepares crops. Run from anywhere:

    python3 source/scripts/build_assets.py

Inputs live in source/assets/reference/ (owner-supplied, unchanged).
Outputs are written to source/assets/product/ and source/assets/photos/.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

SRC = Path(__file__).resolve().parents[1]
REF = SRC / "assets" / "reference"
PRODUCT = SRC / "assets" / "product"
PHOTOS = SRC / "assets" / "photos"

# Active display corners on each blank plate (TL, TR, BR, BL), in plate pixels.
# Measured by hand from gridded crops; the glossy reflections on B and W
# defeat automatic detection.
SCREEN_QUADS = {
    "B": [(410, 420), (812.5, 434), (802.5, 872.5), (404, 839)],
    "E": [(353, 427), (718, 412), (725, 764), (361, 794)],
    "F": [(367, 321), (885, 321), (885, 804), (367, 804)],
    "W": [(774, 576), (1019, 580), (1016, 834), (771, 816)],
}

SUPERSAMPLE = 3


def perspective_coeffs(dst_quad, src_size):
    """Coefficients mapping output (plate) pixels back to screen-art pixels."""
    w, h = src_size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst_quad, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float)).tolist()


def composite_screen(plate_key, reflection=0.35):
    plate = Image.open(REF / f"plate-{plate_key}.png").convert("RGB")
    art = Image.open(REF / "screen-idle-original.png").convert("RGB")
    quad = SCREEN_QUADS[plate_key]
    s = SUPERSAMPLE
    big = (plate.width * s, plate.height * s)
    coeffs = perspective_coeffs([(x * s, y * s) for x, y in quad], art.size)
    warped = art.transform(big, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = Image.new("L", art.size, 255).transform(big, Image.PERSPECTIVE, coeffs, Image.BILINEAR)
    warped = warped.resize(plate.size, Image.LANCZOS)
    mask = mask.resize(plate.size, Image.LANCZOS)

    # Keep the plate's glass reflections: add back whatever is brighter than
    # the panel's base tone inside the display area.
    p = np.asarray(plate).astype(np.float32)
    m = np.asarray(mask).astype(np.float32) / 255.0
    inside = m > 0.99
    base = np.percentile(p[inside].mean(1), 20)
    glare = np.clip(p.mean(2) - base, 0, None)[..., None]
    glare = np.asarray(Image.fromarray(glare[..., 0].astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))).astype(np.float32)[..., None]
    w = np.asarray(warped).astype(np.float32)
    w = 255 - (255 - w) * (1 - reflection * glare / 255.0)  # screen blend
    out = p * (1 - m[..., None]) + w * m[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def main():
    PRODUCT.mkdir(parents=True, exist_ok=True)
    PHOTOS.mkdir(parents=True, exist_ok=True)
    for key in SCREEN_QUADS:
        composite_screen(key).save(PRODUCT / f"scene-{key}-screen.png")
        print("wrote", f"scene-{key}-screen.png")

    # Knob close-up has no visible display content; copy as-is.
    Image.open(REF / "plate-M.png").convert("RGB").save(PRODUCT / "scene-M-knob.png")

    # Camera close-up for the identity page, cut from the straight-on plate.
    f = Image.open(PRODUCT / "scene-F-screen.png")
    f.crop((327, 115, 927, 527)).save(PHOTOS / "camera-closeup.png")  # camera centred at (627, 235)

    # Circular / arch portraits use the untouched screen artwork.
    Image.open(REF / "screen-idle-original.png").convert("RGB").save(PHOTOS / "character.png")

    # Color fronts and CAD views are used unchanged (transparent PNGs).
    for name in ["front-white", "front-lavender", "front-pink", "cad-front", "cad-side"]:
        im = Image.open(REF / f"{name}.png").convert("RGBA")
        im.crop(im.getbbox()).save(PRODUCT / f"{name}.png")


if __name__ == "__main__":
    main()
