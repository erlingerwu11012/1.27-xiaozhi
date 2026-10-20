#!/usr/bin/env python3
"""One-shot: verify firmware embedded PEM matches server_test_public.pem."""
import base64, hashlib, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

src = (ROOT / "main/spine_ota_crypto.cc").read_text(encoding="utf-8")

# Extract lines inside the C string literal for kSpineOtaPublicKeyPem
lines = []
in_key = False
for line in src.splitlines():
    if "kSpineOtaPublicKeyPem[]" in line:
        in_key = True
    if in_key:
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
        for p in parts:
            lines.append(p.replace("\\n", "\n"))
        if ";" in line and in_key and lines:
            break

pem_embedded = "".join(lines)

pem_file = (ROOT / "main/certs/spine_ota_server_test_public.pem").read_text(encoding="utf-8")

def spki_fp(pem_str):
    raw = [l for l in pem_str.encode().splitlines() if not l.startswith(b"-----")]
    der = base64.b64decode(b"".join(raw))
    return hashlib.sha256(der).hexdigest(), der

fp_e, der_e = spki_fp(pem_embedded)
fp_f, der_f = spki_fp(pem_file)

EXPECTED = "4936f22629bad05b7e488bfa676930bd115e322f302e7a951e463da6dba95d2f"

print(f"embedded SPKI SHA-256 : {fp_e}")
print(f"file     SPKI SHA-256 : {fp_f}")
print(f"expected              : {EXPECTED}")
print(f"DER bytes identical   : {der_e == der_f}")

ok = True
if fp_e != EXPECTED:
    print("FAIL: embedded fingerprint mismatch", file=sys.stderr)
    ok = False
if fp_f != EXPECTED:
    print("FAIL: file fingerprint mismatch", file=sys.stderr)
    ok = False
if der_e != der_f:
    print("FAIL: DER bytes differ between source and file", file=sys.stderr)
    ok = False

if ok:
    print("ALL CONSISTENCY CHECKS PASSED")
    sys.exit(0)
else:
    sys.exit(1)
