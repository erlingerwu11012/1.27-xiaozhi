"""Mix VO + music + SFX on the shared timeline.json -> audio/mix/final_mix.wav (48 kHz stereo) + stems.

- VO placed at the cue times from timeline.json (voice-first: these times built the picture edit too)
- "某智能设备" (D) lines get a narrow-band, slightly faster, flat robotic treatment
- music ducks ~10 dB under any VO (sidechain-style envelope, 0.15 s attack / 0.6 s release)
- SFX: lead silence trimmed, peak-normalised per sound, placed at timeline cues
- loudness normalised later at mux time (ffmpeg loudnorm -14 LUFS)
"""
import json, os, subprocess
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
A = os.path.join(ROOT, "audio")
SR = 48000
TL = json.load(open(os.path.join(ROOT, "src", "timeline.json"), encoding="utf-8"))
S = {s["id"]: s for s in TL["shots"]}
N = int((TL["duration"] + 0.5) * SR)
BOOT_OGG = os.path.join(ROOT, "assets", "boot.ogg")


def load(p, sr=SR):
    if not p.endswith(".wav") or True:
        tmp = os.path.join(A, "work", os.path.splitext(os.path.basename(p))[0] + "_48k.wav")
        if not os.path.exists(tmp) or os.path.getmtime(tmp) < os.path.getmtime(p):
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p, "-ar", str(sr), "-ac", "2", tmp], check=True)
        p = tmp
    x, _ = sf.read(p, dtype="float32")
    return x if x.ndim == 2 else np.stack([x, x], 1)


def db(v): return 10 ** (v / 20)


def place(bus, x, t, gain=1.0):
    i = int(round(t * SR))
    if i < 0: x, i = x[-i:], 0
    n = min(len(x), len(bus) - i)
    if n > 0: bus[i:i + n] += x[:n] * gain


def trim_lead(x, thr=0.004):
    idx = np.argmax(np.abs(x).max(1) > thr)
    return x[max(0, idx - int(0.01 * SR)):]


def norm_peak(x, peak_db):
    return x * (db(peak_db) / (np.abs(x).max() + 1e-9))


def fade(x, fin=0.0, fout=0.0):
    x = x.copy()
    if fin: k = int(fin * SR); x[:k] *= np.linspace(0, 1, k)[:, None]
    if fout: k = int(fout * SR); x[-k:] *= np.linspace(1, 0, k)[:, None]
    return x


def robot(x):
    """some-smart-device voice: band-limit 350-3200 Hz, 8% faster, light saturation, flat."""
    m = x.mean(1)
    m = resample_poly(m, 25, 27)                                  # ~8% faster (pitch up slightly, more mechanical)
    m = sosfilt(butter(4, [350, 3200], "bandpass", fs=SR, output="sos"), m)
    m = np.tanh(m * 2.2) / np.tanh(2.2)
    return np.stack([m, m], 1).astype("float32") * 0.8


def build():
    vo = np.zeros((N, 2), "float32"); mus = np.zeros((N, 2), "float32"); sfx = np.zeros((N, 2), "float32"); amb = np.zeros((N, 2), "float32")
    active = np.zeros(N, bool)
    # ---------------- VO
    for c in TL["vo"]:
        x = load(os.path.join(A, "vo", c["id"] + ".wav"))
        x = trim_lead(x, 0.002)
        g = 1.0
        if c["who"] == "D": x = robot(x)
        if c["id"] == "L10": g = 0.7                              # the whispered wake word
        x = norm_peak(x, -3.0) * g
        place(vo, x, c["start"])
        i0, i1 = int(c["start"] * SR), int(c["start"] * SR) + len(x)
        active[i0:min(N, i1)] = True
    # ---------------- music
    a = load(os.path.join(A, "music", "cueA_cold.m4a"))
    a = fade(a[: int((S["S06"]["end"] - 1.5) * SR)], 0.8, 3.5)    # silent beat at the end of S06
    place(mus, norm_peak(a, -6), 0.0)
    b = load(os.path.join(A, "music", "cueB_warm.m4a"))
    b_len = S["S18"]["start"] + 1.5 - S["S07"]["start"]
    b = fade(b[: int(b_len * SR)], 1.2, 2.5)
    place(mus, norm_peak(b, -5), S["S07"]["start"])
    c = load(os.path.join(A, "music", "cueC_end.m4a"))
    c = fade(c[: int((TL["duration"] - S["S18"]["start"] + 0.5) * SR)], 1.5, 4.0)
    place(mus, norm_peak(c, -5), S["S18"]["start"])
    # ducking envelope
    env = np.where(active, db(-10), 1.0).astype("float32")
    att, rel = int(0.15 * SR), int(0.6 * SR)
    sm = env.copy()
    for i in range(1, N):                                      # one-pole smoother (fast down, slow up)
        k = 1 / att if sm[i - 1] > env[i] else 1 / rel
        sm[i] = sm[i - 1] + (env[i] - sm[i - 1]) * k
    mus *= sm[:, None]
    # ---------------- ambience beds
    rn = norm_peak(load(os.path.join(A, "sfx", "room_night.wav")), -26)
    bed = np.concatenate([rn] * int(np.ceil(S["S07"]["start"] / (len(rn) / SR) + 1)))[: int(S["S07"]["start"] * SR)]
    place(amb, fade(bed, 1.0, 1.5), 0.0)
    birds = norm_peak(load(os.path.join(A, "sfx", "birds.wav")), -24)
    place(amb, fade(birds[: int((S["S17"]["end"] - S["S17"]["start"]) * SR)], 0.6, 0.8), S["S17"]["start"])
    # ---------------- SFX
    PEAK = {"door_unlock": -10, "chime_cold": -12, "error_beep": -14, "lamp_click": -12, "keys": -10, "soft_chime": -14,
            "light_off": -12, "curtain": -18, "typing": -16, "switch": -16}
    for s in TL["shots"]:
        for e in s["sfx"]:
            if e["name"] in ("birds",): continue
            if e["name"] == "boot":
                x = load(BOOT_OGG)
                # original boot clip, retimed 1.6x to match the retimed boot frames
                tmp = os.path.join(A, "work", "boot_1p6.wav")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", BOOT_OGG, "-filter:a", "atempo=1.6", "-ar", str(SR), "-ac", "2", tmp], check=True)
                x = sf.read(tmp, dtype="float32")[0]
                place(sfx, norm_peak(x, -9), s["start"])
                continue
            x = trim_lead(load(os.path.join(A, "sfx", e["name"] + ".wav")))
            if e["name"] == "curtain": x = fade(x[: int(3.2 * SR)], 0.3, 1.0)
            if e["name"] == "switch": x = fade(x[: int(2.0 * SR)], 0.0, 0.8)
            place(sfx, norm_peak(x, PEAK.get(e["name"], -14)), e["t"])
    mix = vo + mus * 0.9 + sfx + amb
    peak = np.abs(mix).max()
    if peak > 0.98: mix *= 0.98 / peak
    out = os.path.join(A, "mix"); os.makedirs(out, exist_ok=True)
    for name, x in (("final_mix", mix), ("stem_vo", vo), ("stem_music", mus), ("stem_sfx", sfx + amb)):
        sf.write(os.path.join(out, name + ".wav"), x, SR, subtype="PCM_24")
    return mix, vo, mus


if __name__ == "__main__":
    mix, vo, mus = build()
    # report: music level while VO speaks vs. when not (ducking check, since nobody here can listen)
    w = SR // 2
    print("dur", len(mix) / SR)
    for name, x in (("mix", mix), ("vo", vo), ("music", mus)):
        r = [20 * np.log10(np.sqrt((x[i:i + w] ** 2).mean()) + 1e-9) for i in range(0, len(x) - w, w)]
        print(f"{name:6s}", " ".join(f"{v:4.0f}" for v in r[:240]))
