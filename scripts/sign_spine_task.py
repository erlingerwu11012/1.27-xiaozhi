#!/usr/bin/env python3
"""Development / lab-only tool to sign update_spine task JSON with the DEV ES256 key.

Do NOT use this for production signing. Production private keys must live only in
server-side secret config — never in the device repo, web frontend, or logs.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from spine_ota_canonical import build_canonical  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="DEV ONLY: sign update_spine task JSON (ES256 / ECDSA P-256)"
    )
    ap.add_argument("--task-json", type=Path, required=True, help="JSON without signature")
    ap.add_argument(
        "--private-key",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "main/certs/spine_ota_dev_private.pem",
        help="Development private key path (never a production key)",
    )
    ap.add_argument("--out", type=Path, help="Write signed task JSON")
    args = ap.parse_args()

    task = json.loads(args.task_json.read_text(encoding="utf-8"))
    canonical = build_canonical(task)
    key = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
    der_sig = key.sign(canonical.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der_sig)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    task["signature"] = base64.b64encode(raw).decode("ascii")
    text = json.dumps(task, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
