"""Deploy only the three speech emoji files, with source guards and a backup."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


payload = json.loads(base64.b64decode("@@PAYLOAD@@"))
base = Path("/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server")
allowed = {
    "core/providers/tts/official/prompt.py",
    "core/providers/tts/official/compiler.py",
    "core/utils/textUtils.py",
}
if set(payload) != allowed:
    raise RuntimeError("Unexpected deployment paths")

prepared = {}
manifest = {}
for relative, record in payload.items():
    path = base / relative
    current = path.read_bytes()
    if hashlib.sha256(current).hexdigest() != record["before_sha256"]:
        raise RuntimeError("Server source changed: " + relative)
    content = base64.b64decode(record["content"])
    compile(content.decode("utf-8"), str(path), "exec")
    prepared[relative] = content
    manifest[relative] = {
        "before_sha256": record["before_sha256"],
        "after_sha256": hashlib.sha256(content).hexdigest(),
    }

# Compile the new regular expression without importing production app modules.
tree = ast.parse(prepared["core/utils/textUtils.py"].decode("utf-8"))
pattern = next(
    node.value.args[0].value
    for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "_DISPLAY_EMOJI_PATTERN" for t in node.targets)
)
re.compile(pattern)

processes = json.loads(subprocess.run(
    ["pm2", "jlist"], check=True, capture_output=True, text=True, timeout=20
).stdout)
process = next(p for p in processes if p["name"] == "xiaozhi-server")
if process["pm2_env"].get("pm_cwd") != str(base):
    raise RuntimeError("Unexpected xiaozhi-server working directory")

stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-utc")
backup = base.parent.parent / "docs/deployments/artifacts" / ("tts-no-emoji-" + stamp)
backup.mkdir(parents=True, exist_ok=False)
for relative in prepared:
    saved = backup / "before" / relative
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base / relative, saved)
    staged = backup / "delivery" / relative
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(prepared[relative])
(backup / "manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)

# Run isolated text/queue regression checks before touching the running service.
regression_source = base64.b64decode("@@REGRESSION@@").decode("utf-8")
(backup / "regression.py").write_text(regression_source, encoding="utf-8")
regression = subprocess.run(
    [sys.executable, "-", str(backup / "delivery"), str(base)],
    input=regression_source, capture_output=True, text=True, timeout=60
)
(backup / "regression.txt").write_text(
    regression.stdout + regression.stderr, encoding="utf-8"
)
if regression.returncode:
    print(regression.stdout + regression.stderr)
    raise RuntimeError("Regression checks failed; running source is unchanged")
for relative, record in payload.items():
    if hashlib.sha256((base / relative).read_bytes()).hexdigest() != record["before_sha256"]:
        raise RuntimeError("Server source changed during staging: " + relative)

changed = []
try:
    for relative, content in prepared.items():
        path = base / relative
        temporary = path.with_name(path.name + ".no-emoji-new")
        temporary.write_bytes(content)
        shutil.copystat(path, temporary)
        # Give Python a fresh mtime as well as the new source bytes.
        os.utime(temporary, None)
        os.replace(temporary, path)
        changed.append(relative)
    subprocess.run(
        ["pm2", "restart", "xiaozhi-server"],
        check=True, capture_output=True, text=True, timeout=60
    )
except Exception:
    for relative in changed:
        shutil.copy2(backup / "before" / relative, base / relative)
    subprocess.run(
        ["pm2", "restart", "xiaozhi-server"],
        capture_output=True, text=True, timeout=60
    )
    raise

receipt = {
    "deployed_at_utc": datetime.now(timezone.utc).isoformat(),
    "backup": str(backup),
    "syntax": "passed",
    "regex_compile": "passed",
    "regression": "10 tests passed",
    "restart": "requested",
    "files": manifest,
}
(backup / "receipt.json").write_text(
    json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, ensure_ascii=False))
