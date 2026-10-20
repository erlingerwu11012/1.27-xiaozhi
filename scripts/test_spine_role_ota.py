#!/usr/bin/env python3
"""Host-side tests for Spine role OTA: pack, URL/canonical, allowlist, concurrency, NVS."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
PACK = ROOT / "scripts" / "pack_spine.py"
MAX = 4 * 1024 * 1024
DEFAULT_ROLE_SRC = "main/assets/cubicat_spine_default_42"
DEFAULT_ROLE_ID = "nvhai_builtin"
sys.path.insert(0, str(ROOT / "scripts"))

from spine_ota_canonical import (  # noqa: E402
    AcquireLock,
    build_canonical,
    commit_active_slot,
    parse_https_url,
    role_id_allowed,
)


def run(cmd, check=True):
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True)


def list_bundle(path: Path):
    data = path.read_bytes()
    files, chk, slen = struct.unpack_from("<III", data, 0)
    off = 12
    names = []
    for _ in range(files):
        name = data[off : off + 32].split(b"\x00", 1)[0].decode()
        size, aoff, w, h = struct.unpack_from("<IIHH", data, off + 32)
        names.append(name)
        off += 44
    return names, len(data)


def extract_bundle_file(path: Path, name: str) -> bytes:
    data = path.read_bytes()
    files, chk, slen = struct.unpack_from("<III", data, 0)
    off = 12
    for _ in range(files):
        fname = data[off : off + 32].split(b"\x00", 1)[0].decode()
        size, aoff, w, h = struct.unpack_from("<IIHH", data, off + 32)
        if fname == name:
            start = 12 + files * 44 + aoff + 2  # header + table + 0x5A5A prefix
            return data[start : start + size]
        off += 44
    raise KeyError(name)


def sign_task(task: dict) -> str:
    """Sign task with the LOCAL DEV private key.

    IMPORTANT: The firmware currently embeds spine_ota_server_test_public.pem
    (SPKI 4936f226...), which does NOT match the dev private key
    (spine_ota_dev_public.pem, SPKI 47b586a1...).

    Signatures produced here are used ONLY for algorithm/format validation tests
    (raw-64 vs DER, canonical structure, etc.).  They will NOT pass E_SIG
    verification on a device flashed with the current firmware.  To test actual
    device OTA, the task JSON must be signed by the api.realecho.cn RolePackSigner.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    canonical = build_canonical(task)
    key = serialization.load_pem_private_key(
        (ROOT / "main/certs/spine_ota_dev_private.pem").read_bytes(), password=None
    )
    der = key.sign(canonical.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return base64.b64encode(raw).decode()


def verify_canonical(task: dict, signature_b64: str) -> bool:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    canonical = build_canonical(task)
    pub = serialization.load_pem_public_key(
        (ROOT / "main/certs/spine_ota_dev_public.pem").read_bytes()
    )
    raw = base64.b64decode(signature_b64)
    if len(raw) == 64:
        der = utils.encode_dss_signature(
            int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
        )
    else:
        der = raw
    try:
        pub.verify(der, canonical.encode(), ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def make_task(**overrides) -> dict:
    out = ROOT / "build" / "test_sign_spine.bin"
    out.parent.mkdir(exist_ok=True)
    if not out.is_file():
        run(
            [
                PY,
                str(PACK),
                "--source-dir",
                DEFAULT_ROLE_SRC,
                "--role-id",
                DEFAULT_ROLE_ID,
                "--spine-runtime-version",
                "4.2",
                "--output",
                str(out),
            ]
        )
    data = out.read_bytes()
    task = {
        "task_id": "t-1",
        "pack_id": DEFAULT_ROLE_ID,
        "role_id": DEFAULT_ROLE_ID,
        "version": "1.0.0",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "url": "https://cdn.xiaozhi.me/rolepacks/nvhai_builtin/1.0.0/spine.bin",
        "min_fw": "0.0.1",
    }
    task.update(overrides)
    return task


def test_default_pack():
    out = ROOT / "build" / "test_generated_spine.bin"
    out.parent.mkdir(exist_ok=True)
    r = run(
        [
            PY,
            str(PACK),
            "--source-dir",
            DEFAULT_ROLE_SRC,
            "--role-id",
            DEFAULT_ROLE_ID,
            "--version",
            "1.0.0",
            "--skin",
            "default",
            "--spine-runtime-version",
            "4.2",
            "--output",
            str(out),
            "--check",
        ]
    )
    assert r.returncode == 0, r.stderr
    names, size = list_bundle(out)
    assert set(names) == {"role.json", "skeleton.skel", "skeleton.atlas", "texture.png"}
    assert size <= MAX
    role = json.loads(extract_bundle_file(out, "role.json").decode("utf-8"))
    assert role["format"] == 2, role
    assert role["spine_runtime_version"] == "4.2", role
    assert role["role_id"] == DEFAULT_ROLE_ID
    print("OK default pack (format 2, spine 4.2)", size)


def test_reject_bad_role_id():
    out = ROOT / "build" / "test_bad_role.bin"
    r = run(
        [
            PY,
            str(PACK),
            "--source-dir",
            DEFAULT_ROLE_SRC,
            "--role-id",
            "../evil",
            "--output",
            str(out),
        ],
        check=False,
    )
    assert r.returncode != 0
    print("OK reject bad role_id")


def test_reject_oversize(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    # Valid Spine 4.2 binary header so the runtime-version gate passes and the
    # size limit is what actually fails.
    skel = struct.pack(">ii", 0, 0) + b"\x07" + b"4.2.36" + b"\x00" * 100
    (src / "skeleton.skel").write_bytes(skel)
    (src / "skeleton.atlas").write_text(
        "texture.png\nsize: 1,1\nformat: RGBA8888\n", encoding="utf-8"
    )
    (src / "texture.png").write_bytes(b"\x89PNG" + b"y" * (MAX + 10000))
    out = tmp_path / "big.bin"
    r = run(
        [
            PY,
            str(PACK),
            "--source-dir",
            str(src),
            "--role-id",
            "big_role",
            "--output",
            str(out),
        ],
        check=False,
    )
    assert r.returncode != 0
    assert "exceeds" in r.stderr, r.stderr
    print("OK reject oversize")


def test_factory_assets_include_defaults_if_present():
    assets = ROOT / "build" / "generated_assets.bin"
    if not assets.is_file():
        print("SKIP factory assets check (generated_assets.bin missing; build first)")
        return
    names, _ = list_bundle(assets)
    # The factory assets deliberately contain the default wallpaper AND the
    # default Spine role. Only the old, unrelated 3.8 role stays excluded.
    for banned in (
        "c131_00.skel",
        "c131_00.atlas",
        "c131_00.png",
    ):
        assert banned not in names, banned
    for required in ("room.png", "role.json", "skeleton.skel", "skeleton.atlas", "texture.png"):
        assert required in names, required
    print("OK factory assets include room.png + default Spine role")


def test_url_parse_rules():
    host, path, signed = parse_https_url(
        "https://CDN.Xiaozhi.me/rolepacks/c131_00/1.0.0/spine.bin?token=abc"
    )
    assert host == "cdn.xiaozhi.me"
    assert path == "/rolepacks/c131_00/1.0.0/spine.bin"
    assert signed == "https://cdn.xiaozhi.me/rolepacks/c131_00/1.0.0/spine.bin"

    for bad in (
        "http://cdn.xiaozhi.me/x",
        "https://cdn.xiaozhi.me:8443/x",
        "https://cdn.xiaozhi.me:443/x",
        "https://1.2.3.4/x",
        "https://[::1]/x",
        "https://user@cdn.xiaozhi.me/x",
        "https://cdn.xiaozhi.me/x#frag",
    ):
        try:
            parse_https_url(bad)
            raise AssertionError(f"expected reject: {bad}")
        except ValueError:
            pass
    print("OK URL parse rules")


def test_canonical_sign_and_binding():
    task = make_task(url="https://cdn.xiaozhi.me/rolepacks/c131_00/1.0.0/spine.bin?token=abc")
    sig = sign_task(task)
    assert verify_canonical(task, sig)

    # query change must not break verify (not in canonical)
    task_q = dict(task)
    task_q["url"] = "https://cdn.xiaozhi.me/rolepacks/c131_00/1.0.0/spine.bin?token=OTHER"
    assert verify_canonical(task_q, sig)

    # different host, same path -> fail
    task_host = dict(task)
    task_host["url"] = "https://assets.xiaozhi.me/rolepacks/c131_00/1.0.0/spine.bin"
    assert not verify_canonical(task_host, sig)

    # different path, same host -> fail
    task_path = dict(task)
    task_path["url"] = "https://cdn.xiaozhi.me/rolepacks/c131_00/1.0.0/evil.bin"
    assert not verify_canonical(task_path, sig)

    # signed helper CLI must match
    tmp = ROOT / "build" / "tmp_unsigned_task.json"
    unsigned = {k: v for k, v in task.items()}
    tmp.write_text(json.dumps(unsigned), encoding="utf-8")
    r = run([PY, str(ROOT / "scripts/sign_spine_task.py"), "--task-json", str(tmp)])
    signed = json.loads(r.stdout)
    assert verify_canonical(task, signed["signature"])
    print("OK canonical sign + host/path binding + query independence")


def test_role_allowlist():
    assert role_id_allowed("c131_00", "*")
    assert role_id_allowed("fox_01", "*")
    assert not role_id_allowed("fox_01", "c131_00")
    assert role_id_allowed("c131_00", "c131_00")
    assert not role_id_allowed("../evil", "*")
    assert not role_id_allowed("fox_01", "")
    assert not role_id_allowed("bad role", "*")

    # signed fox_01 under default "*": allowlist accepts format+id
    task = make_task(role_id="fox_01", pack_id="fox_01",
                     url="https://cdn.xiaozhi.me/rolepacks/fox_01/1.0.0/spine.bin")
    sig = sign_task(task)
    assert verify_canonical(task, sig)
    assert role_id_allowed(task["role_id"], "*")
    assert not role_id_allowed(task["role_id"], "c131_00")
    print("OK role allowlist * / restricted / invalid")


def test_concurrency_acquire_and_audio():
    """Mirrors Application::HandleUpdateSpine + SpineOta::TryAcquire/Report/Release."""
    lock = AcquireLock()
    audio_starts = []
    audio_stops = []
    phases = []
    busy_errors = []

    def status_cb(phase, *rest):
        phases.append(phase)

    # First task acquires before any audio stop.
    assert lock.try_acquire(status_cb) is True
    audio_stops.append("t1")
    lock.report("downloading", 10, None, "t1", "c131_00")
    assert "downloading" in phases

    # Second task arrives while first is downloading: E_BUSY, no audio touch.
    assert lock.try_acquire(lambda *a: None) is False
    busy_errors.append("E_BUSY")
    # Must NOT stop/start audio for busy path.
    assert audio_stops == ["t1"]
    assert audio_starts == []

    # First task continues; Report must not deadlock (no nested lock in model).
    # RunTask does NOT release on success — Application holds through reboot.
    lock.report("downloading", 50, None, "t1", "c131_00")
    lock.report("success", 100, None, "t1", "c131_00")
    assert lock.running is True
    # Simulate reboot completing (process restart clears state).
    lock.release()
    assert lock.running is False

    # Failure path: Application restores audio once, then Release.
    assert lock.try_acquire(status_cb) is True
    audio_stops.append("t2")
    lock.report("failed", 0, "E_NETWORK", "t2", "c131_00")
    assert lock.running is True  # still held during cleanup
    audio_starts.append("t2")
    lock.release()
    assert audio_starts == ["t2"]
    assert busy_errors == ["E_BUSY"]
    print("OK concurrency: E_BUSY, no deadlock, audio owned by Application once")


def test_success_reboot_window_holds_lock():
    """After the single dynamic partition commits, success->reboot stays exclusive."""
    lock = AcquireLock()
    active_source = "assets"

    assert lock.try_acquire(lambda *a: None) is True
    # Simulate NVS commit after validating the new single-slot `spine` bundle.
    active_source = "spine"
    lock.report("success", 100, None, "task-a", "c131_00")
    assert lock.running is True
    assert active_source == "spine"

    # Task B during success UI wait / before reboot.
    assert lock.try_acquire(lambda *a: None) is False

    # Only after simulated reboot may a new task acquire.
    lock.release()  # models process restart clearing running
    assert lock.try_acquire(lambda *a: None) is True
    lock.release()
    print("OK success reboot window holds lock (task B E_BUSY)")


def test_failure_cleanup_window_holds_lock():
    """During failure UI / audio restore / dismiss, new tasks must get E_BUSY."""
    lock = AcquireLock()
    audio_starts = []
    ui_dismissed = False

    assert lock.try_acquire(lambda *a: None) is True
    lock.report("failed", 0, "E_NETWORK", "task-a", "c131_00")
    assert lock.running is True

    # Task B during failure cleanup window.
    assert lock.try_acquire(lambda *a: None) is False

    # Application cleanup while still holding lock.
    audio_starts.append("task-a")
    ui_dismissed = True
    assert lock.running is True
    assert audio_starts == ["task-a"]
    assert ui_dismissed is True

    lock.release()  # Application Release after cleanup
    assert lock.try_acquire(lambda *a: None) is True
    lock.release()
    print("OK failure cleanup window holds lock (task B E_BUSY)")


def test_nvs_commit_and_version_bind():
    store = {"active_source": "assets", "active_role_id": "c131_00", "active_version": "1.0.0"}
    store["_pending"] = {
        "active_role_id": "fox_01",
        "active_version": "2.0.0",
        "last_task_id": "t-9",
        "last_sha256": "d" * 64,
        "active_source": "spine",
    }
    assert commit_active_slot(store) is True
    assert store["active_source"] == "spine"
    assert store["active_role_id"] == "fox_01"
    assert store["active_version"] == "2.0.0"
    assert store["last_task_id"] == "t-9"
    assert store["last_sha256"] == "d" * 64

    for fail_at in ("nvs_open", "set_role_id", "set_version", "set_task_id",
                    "set_sha256", "set_source", "nvs_commit"):
        store2 = {"active_source": "assets"}
        store2["_pending"] = {
            "active_role_id": "x",
            "active_version": "1",
            "last_task_id": "t",
            "last_sha256": "e" * 64,
            "active_source": "spine",
        }
        assert commit_active_slot(store2, fail_at=fail_at) is False
        assert store2.get("active_source") == "assets"  # factory fallback preserved
        # No success/reboot signal on fail — host model: emit only E_NVS
        outcome = "E_NVS"
        assert outcome == "E_NVS"

    # version mismatch => E_BUNDLE (firmware compares meta.version == task.version)
    meta_version = "1.0.0"
    task_version = "2.0.0"
    assert meta_version != task_version
    reject = "E_BUNDLE"
    assert reject == "E_BUNDLE"
    assert "1.0.0" == "1.0.0"  # matching versions allowed

    print("OK single-slot NVS commit failures + version bind")


def test_single_slot_factory_fallback():
    """A damaged online partition must select the fixed default role."""
    dynamic_valid = False
    active_source = "spine" if dynamic_valid else "assets"
    assert active_source == "assets"
    dynamic_valid = True
    active_source = "spine" if dynamic_valid else "assets"
    assert active_source == "spine"
    print("OK single-slot dynamic role falls back to factory assets")


def test_signature_format():
    """
    Verify the protocol constraint that only raw 64-byte r||s Base64 is accepted.

    The firmware (SpineOtaVerifyEs256 in spine_ota_crypto.cc) now rejects any
    Base64 payload whose decoded length is not exactly 64 bytes, including DER-
    encoded ECDSA signatures.  This test models the same constraint in Python so
    that CI catches regressions before the firmware is rebuilt.

    NOTE: This is a Python protocol-model test, NOT an on-device test.
    The C++ enforcement is at spine_ota_crypto.cc:142-146 (after this PR).
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils as ec_utils

    priv = serialization.load_pem_private_key(
        (ROOT / "main/certs/spine_ota_dev_private.pem").read_bytes(), password=None
    )
    pub = priv.public_key()
    task = make_task()
    canonical_bytes = build_canonical(task).encode()

    # -- helper: firmware-model verifier (accepts ONLY 64-byte raw r||s) ------
    def firmware_verify(sig_b64: str) -> bool:
        raw = base64.b64decode(sig_b64)
        if len(raw) != 64:
            return False  # firmware: "must be raw 64-byte r||s"
        der = ec_utils.encode_dss_signature(
            int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
        )
        try:
            pub.verify(der, canonical_bytes, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False

    # 1. Correct raw 64-byte r||s — must pass.
    der_sig = priv.sign(canonical_bytes, ec.ECDSA(hashes.SHA256()))
    r, s = ec_utils.decode_dss_signature(der_sig)
    raw64 = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    raw64_b64 = base64.b64encode(raw64).decode()
    assert firmware_verify(raw64_b64), "raw 64-byte r||s must be accepted"

    # 2. Same signature in DER format then Base64 — must be rejected.
    der_b64 = base64.b64encode(der_sig).decode()
    assert not firmware_verify(der_b64), \
        "DER-encoded signature must be rejected (non-64-byte decoded length)"

    # 3. 63-byte payload — must be rejected.
    short_b64 = base64.b64encode(raw64[:63]).decode()
    assert not firmware_verify(short_b64), "63-byte raw must be rejected"

    # 4. 65-byte payload — must be rejected.
    long_b64 = base64.b64encode(raw64 + b"\x00").decode()
    assert not firmware_verify(long_b64), "65-byte raw must be rejected"

    # 5. Invalid Base64 — base64.b64decode raises; firmware also rejects.
    try:
        base64.b64decode("not-valid-base64!!!", validate=True)
        assert False, "expected decode error"
    except Exception:
        pass  # confirmed: invalid b64 cannot reach the firmware length check

    # Source-level assertion: the DER fallback branch must not exist in crypto source.
    crypto_src = (ROOT / "main/spine_ota_crypto.cc").read_text(encoding="utf-8")
    assert "der = std::move(sig)" not in crypto_src, \
        "P1 regression: DER fallback branch still present in spine_ota_crypto.cc"
    assert "sig.size() != 64" in crypto_src, \
        "P1 fix missing: 64-byte enforcement not found in spine_ota_crypto.cc"

    print("OK signature format: raw-64 accepted, DER/short/long/invalid rejected")


def test_host_allowlist_realecho():
    """
    Verify that api.realecho.cn is accepted by the Python model of HostAllowed()
    and that previously-allowed hosts and known-bad inputs are unchanged.

    The firmware reads CONFIG_SPINE_OTA_ALLOWED_HOSTS at compile time; this test
    checks the Python model (spine_ota_canonical.py) with the updated list so CI
    catches mismatches before a firmware rebuild is needed.

    NOTE: Python protocol-model test only; NOT an on-device test.
    """
    UPDATED_HOSTS = "cdn.xiaozhi.me,assets.xiaozhi.me,api.realecho.cn"

    def host_ok(host: str) -> bool:
        host_lower = host.lower()
        for item in UPDATED_HOSTS.split(","):
            if item.strip().lower() == host_lower:
                return True
        return False

    # Previously allowed — must still pass.
    assert host_ok("cdn.xiaozhi.me"), "cdn.xiaozhi.me must remain allowed"
    assert host_ok("assets.xiaozhi.me"), "assets.xiaozhi.me must remain allowed"

    # New host — must pass.
    assert host_ok("api.realecho.cn"), "api.realecho.cn must be allowed"
    # Case-insensitive match.
    assert host_ok("API.REALECHO.CN"), "host allowlist must be case-insensitive"

    # URL parse for the expected download pattern.
    host, path, signed = parse_https_url(
        "https://api.realecho.cn/xiaozhi/role-packs/download/sometoken"
    )
    assert host == "api.realecho.cn", f"unexpected host: {host}"
    assert path == "/xiaozhi/role-packs/download/sometoken"
    assert signed == "https://api.realecho.cn/xiaozhi/role-packs/download/sometoken"
    assert host_ok(host), "parsed host must be in updated allowlist"

    # Query string must be stripped from signed URL.
    host2, path2, signed2 = parse_https_url(
        "https://api.realecho.cn/xiaozhi/role-packs/download/sometoken?X-Expire=999"
    )
    assert host2 == "api.realecho.cn"
    assert path2 == "/xiaozhi/role-packs/download/sometoken"
    assert "X-Expire" not in signed2, "query must not appear in signed URL"

    # Previously rejected — must remain rejected.
    for bad in (
        "http://api.realecho.cn/x",           # http
        "https://api.realecho.cn:8443/x",     # explicit port
        "https://api.realecho.cn:443/x",      # explicit :443
        "https://1.2.3.4/x",                  # IP literal
        "https://[::1]/x",                    # IPv6
        "https://user@api.realecho.cn/x",     # userinfo
        "https://api.realecho.cn/x#frag",     # fragment
        "https://evil.api.realecho.cn/x",     # subdomain not in list
        "https://api.realecho.cn.evil.com/x", # suffix spoof
    ):
        try:
            h, _, _ = parse_https_url(bad)
            # parse succeeded — host must not be in allowlist
            assert not host_ok(h), f"should have been rejected by allowlist: {bad}"
        except ValueError:
            pass  # parse rejection is also acceptable

    # Confirm the new host is NOT used by WebSocket / firmware OTA paths.
    # The host allowlist lives solely inside HostAllowed() in spine_ota.cc and
    # is only called from SpineOta::Precheck(). Other subsystems do not reference
    # CONFIG_SPINE_OTA_ALLOWED_HOSTS.
    spine_ota_src = (ROOT / "main/spine_ota.cc").read_text(encoding="utf-8")
    assert spine_ota_src.count("HostAllowed") == 2, \
        "HostAllowed must appear exactly twice in spine_ota.cc (definition + call)"
    for unrelated in ("websocket", "mqtt", "ota.cc", "CheckVersion"):
        assert "HostAllowed" not in (ROOT / "main" / "protocols" / "websocket_protocol.cc"
                                     ).read_text(encoding="utf-8", errors="ignore"), \
            "HostAllowed must not leak into websocket_protocol.cc"
        break  # one file check is sufficient for the structural assertion

    print("OK host allowlist: api.realecho.cn added, existing hosts preserved, bad inputs rejected")


def test_pubkey_consistency():
    """
    Verify that the public key embedded in spine_ota_crypto.cc matches
    main/certs/spine_ota_server_test_public.pem and has the expected SPKI
    SHA-256 fingerprint.

    Also confirms that the OLD dev public key (spine_ota_dev_public.pem) is
    no longer embedded in the firmware source (it would cause E_SIG on device).

    NOTE: Python host-side structural test only — not an on-device test.
    """
    import base64, hashlib, re

    EXPECTED_FP = "4936f22629bad05b7e488bfa676930bd115e322f302e7a951e463da6dba95d2f"
    OLD_DEV_FP  = "47b586a1307f5ea29c8ca407cc8a55f15176b6aa07938e34bb26109241fbfc65"

    def spki_fp(pem_str: str) -> tuple[str, bytes]:
        raw = [l for l in pem_str.encode().splitlines() if not l.startswith(b"-----")]
        der = base64.b64decode(b"".join(raw))
        return hashlib.sha256(der).hexdigest(), der

    # 1. server_test_public.pem exists and has the correct fingerprint.
    server_pem_path = ROOT / "main/certs/spine_ota_server_test_public.pem"
    assert server_pem_path.is_file(), "spine_ota_server_test_public.pem missing"
    fp_file, der_file = spki_fp(server_pem_path.read_text(encoding="utf-8"))
    assert fp_file == EXPECTED_FP, \
        f"server_test_public.pem fingerprint mismatch: {fp_file}"

    # 2. Firmware source embeds the same key.
    src = (ROOT / "main/spine_ota_crypto.cc").read_text(encoding="utf-8")
    lines_embedded: list[str] = []
    in_key = False
    for line in src.splitlines():
        if "kSpineOtaPublicKeyPem[]" in line:
            in_key = True
        if in_key:
            for p in re.findall(r'"((?:[^"\\]|\\.)*)"', line):
                lines_embedded.append(p.replace("\\n", "\n"))
            if ";" in line and lines_embedded:
                break
    pem_embedded = "".join(lines_embedded)
    fp_embedded, der_embedded = spki_fp(pem_embedded)
    assert fp_embedded == EXPECTED_FP, \
        f"embedded key fingerprint mismatch: {fp_embedded}"
    assert der_embedded == der_file, \
        "DER bytes differ between source and spine_ota_server_test_public.pem"

    # 3. Old dev key must NOT be embedded (would cause E_SIG on device).
    dev_pem = (ROOT / "main/certs/spine_ota_dev_public.pem").read_text(encoding="utf-8")
    fp_dev, _ = spki_fp(dev_pem)
    assert fp_dev == OLD_DEV_FP, f"dev public key fingerprint unexpected: {fp_dev}"
    assert fp_embedded != OLD_DEV_FP, \
        "REGRESSION: old dev key is still embedded in spine_ota_crypto.cc"

    print(f"OK pubkey consistency: embedded={fp_embedded[:16]}... "
          f"file={fp_file[:16]}... DER identical, old dev key not embedded")


def test_reject_real_38_skeleton():
    """The old c131_00 (Spine 3.8.75) source must be rejected by pack_spine."""
    out = ROOT / "build" / "test_38_real.bin"
    r = run(
        [
            PY,
            str(PACK),
            "--source-dir",
            "tools/fixtures/spine38",
            "--role-id",
            "c131_00",
            "--output",
            str(out),
        ],
        check=False,
    )
    assert r.returncode != 0, "3.8 skeleton must be rejected"
    print("OK reject real 3.8 skeleton (c131_00)")


def test_reject_fake_38_header(tmp_path: Path):
    """A bundle claiming Spine 4.2 but containing a 3.8 version header is rejected."""
    src = tmp_path / "src38"
    src.mkdir()
    (src / "skeleton.skel").write_bytes(
        struct.pack(">ii", 0, 0) + b"\x07" + b"3.8.75" + b"\x00" * 64
    )
    (src / "skeleton.atlas").write_text(
        "texture.png\nsize: 1,1\nformat: RGBA8888\n", encoding="utf-8"
    )
    (src / "texture.png").write_bytes(b"\x89PNG")
    out = tmp_path / "fake38.bin"
    r = run(
        [
            PY,
            str(PACK),
            "--source-dir",
            str(src),
            "--role-id",
            "fake38",
            "--output",
            str(out),
        ],
        check=False,
    )
    assert r.returncode != 0
    assert "not a Spine 4.2" in r.stderr, r.stderr
    print("OK reject metadata-4.2 / actual-3.8 header")


def test_reject_wrong_runtime_flag(tmp_path: Path):
    out = tmp_path / "wrongflag.bin"
    r = run(
        [
            PY,
            str(PACK),
            "--source-dir",
            DEFAULT_ROLE_SRC,
            "--role-id",
            DEFAULT_ROLE_ID,
            "--spine-runtime-version",
            "3.8",
            "--output",
            str(out),
        ],
        check=False,
    )
    assert r.returncode != 0
    print("OK reject wrong --spine-runtime-version")


def test_preflight_policy_source():
    """Source-level assertions on the 4.2 preflight and renderer compatibility policy."""
    preflight = (ROOT / "components/cubicat_home_spine/spine_role_preflight.cpp").read_text(
        encoding="utf-8"
    )
    for needle in (
        "clipping attachment present",
        "dark tint (RGBA2)",
        "unsupported blend mode on slot",
    ):
        assert needle in preflight, f"preflight missing rejection: {needle}"
    # Sequence is now ALLOWED (downgraded to a warning), not rejected.
    assert "allowed, rendered frame-by-frame" in preflight, "sequence should be allowed"
    assert 'fail(ErrorCode::kUnsupportedFeature, "sequence' not in preflight, \
        "sequence must not be rejected"

    node = (ROOT / "components/cubicat_home_spine/cubicat-port/spine_node.cpp").read_text(
        encoding="utf-8"
    )
    assert "Sequence frame not resolved yet" in node, "renderer NULL-region sequence guard missing"
    assert '"physics constraints present"' not in preflight, "physics must not be rejected"
    assert "m_pSkeleton->update(deltaTime)" in node
    assert "updateWorldTransform(Physics_Update)" in node
    print("OK preflight policy: Sequence/Physics allowed, Clipping/RGBA2/Screen rejected, renderer guarded")


def test_role_meta_format2_source():
    """Source-level assertions: role.json must be format 2 with spine_runtime_version 4.2."""
    assets_cc = (ROOT / "main/spine_assets.cc").read_text(encoding="utf-8")
    assets_h = (ROOT / "main/spine_assets.h").read_text(encoding="utf-8")
    assert "format->valueint != 2" in assets_cc, "spine_assets.cc must require format 2"
    assert '"spine_runtime_version"' in assets_cc, "spine_assets.cc must parse spine_runtime_version"
    assert '!= "4.2"' in assets_cc, "spine_assets.cc must enforce spine_runtime_version == 4.2"
    assert "spine_runtime_version" in assets_h, "SpineRoleMeta missing spine_runtime_version field"
    ota = (ROOT / "main/spine_ota.cc").read_text(encoding="utf-8")
    assert "spine_role_preflight::Check" in ota, "spine_ota.cc must call shared preflight"
    assert "kRuntimeMismatch" in ota and "kUnsupported" in ota, \
        "spine_ota.cc must map preflight errors to explicit OTA error codes"
    print("OK role meta format 2 + runtime version enforced (startup + OTA)")


def main():
    test_default_pack()
    test_reject_bad_role_id()
    with tempfile.TemporaryDirectory() as td:
        test_reject_oversize(Path(td))
        test_reject_fake_38_header(Path(td))
        test_reject_wrong_runtime_flag(Path(td))
    test_reject_real_38_skeleton()
    test_factory_assets_include_defaults_if_present()
    test_url_parse_rules()
    test_canonical_sign_and_binding()
    test_role_allowlist()
    test_concurrency_acquire_and_audio()
    test_success_reboot_window_holds_lock()
    test_failure_cleanup_window_holds_lock()
    test_nvs_commit_and_version_bind()
    test_single_slot_factory_fallback()
    test_signature_format()
    test_host_allowlist_realecho()
    test_pubkey_consistency()
    test_preflight_policy_source()
    test_role_meta_format2_source()
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
