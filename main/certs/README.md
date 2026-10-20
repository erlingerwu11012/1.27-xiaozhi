# Spine OTA signing keys

## Files in this directory

| File | Purpose |
|------|---------|
| `spine_ota_dev_private.pem` | **Local dev only.** Paired with `spine_ota_dev_public.pem`. Used by `scripts/sign_spine_task.py` and host-side algorithm/format tests. **Never commit to any public repo; never use on production devices.** |
| `spine_ota_dev_public.pem` | Old local development public key. SPKI SHA-256: `47b586a1307f5ea29c8ca407cc8a55f15176b6aa07938e34bb26109241fbfc65`. **No longer embedded in firmware** — device OTA with this key will fail E_SIG. |
| `spine_ota_dev_public_uncompressed.bin` | Raw 65-byte uncompressed EC point for `spine_ota_dev_public.pem`. Not used by firmware. |
| `spine_ota_server_test_public.pem` | **Current firmware key.** Paired with the current `api.realecho.cn` RolePackSigner service. The project owner has authorized keeping this service and key for the public release. SPKI SHA-256: `4936f22629bad05b7e488bfa676930bd115e322f302e7a951e463da6dba95d2f`. Embedded in `spine_ota_crypto.cc` as `kSpineOtaPublicKeyPem`. |

## Security rules

1. **Private keys must never enter this repository or be embedded in firmware.**
   Only public keys (SubjectPublicKeyInfo PEM) are stored here.
2. The public release intentionally keeps the current Realecho OTA service and
   its matching public key. The matching private key remains server-side and
   must never be copied into this repository or distributed with firmware.
3. The `.gitignore` entry `main/certs/*_private.pem` prevents accidental commits
   of private key files. Do not remove or weaken this rule.
4. Firmware public key changes require a full USB reflash because the partition
   table has a single factory app slot (no ota_0/ota_1).

## How to verify the embedded public key matches a .pem file

```
python scripts/_verify_pubkey.py
```

This script checks that `kSpineOtaPublicKeyPem` in `spine_ota_crypto.cc` has the
same SPKI SHA-256 as `spine_ota_server_test_public.pem` and that the DER bytes
are byte-for-byte identical.
