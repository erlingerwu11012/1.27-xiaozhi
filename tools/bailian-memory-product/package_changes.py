"""Create a bounded overlay from the tracked source snapshot, without secrets."""
from pathlib import Path
import hashlib
import json
import tarfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "tmp" / "bailian-memory-product"


def package(name):
    mirror = WORK / name
    original = {}
    with tarfile.open(WORK / f"{name}-source.tar.gz") as archive:
        for entry in archive.getmembers():
            if entry.isfile():
                original[entry.name] = hashlib.sha256(archive.extractfile(entry).read()).hexdigest()
    changed = []
    for path in mirror.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(mirror).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if original.get(relative) != digest:
            changed.append((relative, digest))
    with tarfile.open(WORK / f"{name}-overlay.tar.gz", "w:gz") as archive:
        for relative, _ in sorted(changed):
            archive.add(mirror / relative, arcname=relative)
    (WORK / f"{name}-changes.json").write_text(json.dumps(dict(changed), indent=2), encoding="utf-8")
    print(f"{name}: {len(changed)} changed files")


if __name__ == "__main__":
    package("server")
    package("gateway")
