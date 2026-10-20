"""Capture source hashes before implementation; never capture runtime memory data."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tmp" / "bailian-memory-product"


def capture():
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / "firmware-baseline.json"
    if destination.exists():
        raise SystemExit("Baseline already exists; refusing to overwrite")
    files = {}
    for base in [ROOT / "main", ROOT / "tools"]:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".cc", ".h", ".cpp", ".py", ".json", ".txt"}:
                files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True)
    destination.write_text(json.dumps({"head": head, "status_before": status, "sha256": files}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Captured {len(files)} source hashes")


if __name__ == "__main__":
    capture()
