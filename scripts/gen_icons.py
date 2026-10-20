import struct, zlib, os
from pathlib import Path

def make_png(pixels_20x20):
    width, height = 20, 20
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            raw += pixels_20x20[y][x]
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    hdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', hdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')

W = b'\xff\xe7\xc4\xff'  # warm white RGBA
T = b'\x00\x00\x00\x00'  # transparent


def draw_wifi(pixels, arcs=3, right_side=False):
    """Draw WiFi arcs with a center dot. arcs=1/2/3 for signal strength."""
    # center dot
    for y in [9, 10]:
        for x in [9, 10]:
            if 0 <= y < 20 and 0 <= x < 20:
                pixels[y][x] = W
    arc_specs = [
        (6, 12, False),   # inner arc r~3
        (20, 30, False),  # middle arc r~5
        (42, 56, False),  # outer arc r~7
    ]
    for i in range(min(arcs, 3)):
        lo, hi, _ = arc_specs[i]
        for y in range(20):
            for x in range(20):
                dx, dy = x - 9.5, y - 9.5
                dist = dx * dx + dy * dy
                if lo <= dist <= hi:
                    if right_side:
                        if x > 10:
                            pixels[y][x] = W
                    else:
                        if x < 10:
                            pixels[y][x] = W


# wifi_off: WIFI arcs + diagonal slash
wifi_off = [[T] * 20 for _ in range(20)]
draw_wifi(wifi_off, arcs=3, right_side=False)
# diagonal slash
for d in range(-1, 7):
    for offset in [(0, 0), (1, 0), (0, 1)]:
        x, y = 8 + d + offset[0], 12 - d + offset[1]
        if 0 <= x < 20 and 0 <= y < 20:
            wifi_off[y][x] = W

# wifi_connected: 3 full WIFI arcs (both sides), strong signal
wifi_connected = [[T] * 20 for _ in range(20)]
# all 3 arcs on both sides of dot
draw_wifi(wifi_connected, arcs=3, right_side=False)
draw_wifi(wifi_connected, arcs=3, right_side=True)

# wifi_config: WIFI arcs with a small gear/gear-like symbol (two circular dots)
wifi_config = [[T] * 20 for _ in range(20)]
draw_wifi(wifi_config, arcs=3, right_side=False)
# Two small dots at the top-right to indicate "configuring"
for dy in range(-2, 3):
    for offset in [(13, 3), (15, 5)]:
        x, y = offset[0] + dy, offset[1] + dy
        if 0 <= x < 20 and 0 <= y < 20:
            wifi_config[y][x] = W
# second dot pair
for dy in range(-2, 3):
    for offset in [(15, 3), (13, 5)]:
        x, y = offset[0] - dy, offset[1] + dy
        if 0 <= x < 20 and 0 <= y < 20:
            wifi_config[y][x] = W

# muted: speaker + cross
muted = [[T] * 20 for _ in range(20)]
# speaker rectangle body
for y in range(6, 15):
    for x in range(2, 7):
        muted[y][x] = W
# speaker cone (triangle)
for y in range(4, 17):
    for x in range(7, min(12, 7 + abs(9 - y) + 1)):
        muted[y][x] = W
# cross lines (2px thick)
for d in range(-2, 6):
    x, y = 12 + d, 3 + d
    if 0 <= x < 20 and 0 <= y < 20:
        muted[y][x] = W
    x, y = 13 + d, 4 + d
    if 0 <= x < 20 and 0 <= y < 20:
        muted[y][x] = W
for d in range(-2, 6):
    x, y = 12 + d, 17 - d
    if 0 <= x < 20 and 0 <= y < 20:
        muted[y][x] = W
    x, y = 13 + d, 16 - d
    if 0 <= x < 20 and 0 <= y < 20:
        muted[y][x] = W

# Compute base directory relative to this script
script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parent
base = repo_root / 'main' / 'assets' / 'cubicat_home' / 'icons'
os.makedirs(str(base), exist_ok=True)

icons = [
    ('wifi_connected.png', wifi_connected),
    ('wifi_config.png', wifi_config),
    ('wifi_off.png', wifi_off),
    ('muted.png', muted),
]

for name, pixels in icons:
    path = base / name
    with open(str(path), 'wb') as f:
        f.write(make_png(pixels))
    print(f'Icon created: {name} ({os.path.getsize(str(path))} bytes)')

print('All icons created OK')
