# Version 2 Partition Table

This version adds an `assets` partition for network-loadable base content and (on the
active ESP-BOX-3 16MB product table) dedicated Spine role A/B slots.

## Active product table: `16m.csv` (ESP32-S3 / 16MB)

**This is the table selected by `sdkconfig` / `sdkconfig.defaults.esp32s3`.**

| Name | Type | Offset | Size | Notes |
|------|------|--------|------|-------|
| nvs | data/nvs | `0x9000` | 16 KB | |
| phy_init | data/phy | `0xd000` | 4 KB | |
| **factory** | app/factory | `0x10000` | **5 MB** | Single app slot — **no firmware A/B OTA** |
| userdata | data/spiffs | `0x510000` | 128 KB | Behavior logs only — do not reuse |
| assets | data/spiffs | `0x530000` | ≈8.81 MB (`0x8D0000`) | Fonts, wake-word, room.png, home JS, icons |
| spine_a | data/`0x40` | `0xE00000` | 1 MB | Role package slot A |
| spine_b | data/`0x41` | `0xF00000` | 1 MB | Role package slot B |

End address: `0x1000000` (exactly 16 MB).

### Important constraints

1. **No `ota_0` / `ota_1` / `otadata`.** Firmware dual-slot OTA is not supported on this table
   (app ≈3.7 MB cannot fit two safe OTA slots alongside assets + spine).
2. **Spine role OTA** writes only `spine_a` / `spine_b` via `update_spine`. Never write role
   packages into `assets`, `factory`, or `userdata`.
3. **Online partition-table migration is not supported.** Devices already flashed with an older
   layout must be migrated with a **one-shot USB / factory full flash**:
   bootloader + partition-table + app + assets + `spine_a` (recommend also initializing `spine_b`).

## Other tables in this folder

Other CSV files (`8m.csv`, `16m_c3.csv`, `32m.csv`, …) may still contain classic
`otadata` + `ota_0`/`ota_1` layouts for different boards. **Do not assume they describe
the current ESP-BOX-3 product build** — always check `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME`.

### Historical v1 16MB (reference only)

- `nvs` / `otadata` / `phy_init` / `model` / `ota_0` (6MB) / `ota_1` (6MB)

## Assets vs Spine

| Partition | Contents |
|-----------|----------|
| assets | Fonts, srmodels / wake-word, `room.png`, home JS, status icons, `index.json` |
| spine_a / spine_b | Role package only: `role.json`, `skeleton.skel`, `skeleton.atlas`, `texture.png` |

Max role package transfer size: **960 KiB (983040 bytes)**.

## Flashing (new layout)

```text
idf.py build flash
# flashes: bootloader, partition-table, app, assets, spine_a
# optional: also flash spine_b with the same default role (see Kconfig FLASH_SPINE_B_DEFAULT)
```

See `docs/SPINE_ROLE_OTA.md` for migration and role OTA details.
