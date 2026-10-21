"""Generate music cues (Sonilo Music) and SFX (Seed Audio) on Higgsfield. Cue lengths come from timeline.json.

python gen_music_sfx.py cost | make [names...]
-> ../../audio/music/<cue>.wav|mp3, ../../audio/sfx/<name>.wav
"""
import json, os, re, subprocess, sys, urllib.request
from synth_voices import HF, ROOT

TL = json.load(open(os.path.join(ROOT, "src", "timeline.json"), encoding="utf-8"))
S = {s["id"]: s for s in TL["shots"]}
A_END = S["S07"]["start"]                 # cold section ends at the silence before the wake word
B_END = S["S18"]["start"]
C_END = TL["duration"]

MUSIC = {
    "cueA_cold": (int(A_END + 2),
        "Cinematic minimal ambient underscore, cold and lonely, slow tempo around 60 bpm, deep soft sub-bass drone, distant sparse "
        "felt-piano notes with long reverb, airy high synth pad, subtle tension, no drums, no vocals. Gradually thins out and ends in near silence."),
    "cueB_warm": (int(B_END - A_END + 3),
        "Warm, intimate cinematic piano piece, no vocals. Opens with only two or three single soft felt-piano notes and silence for about six "
        "seconds, then warm major chords bloom with soft strings, then settles into a gentle lo-fi groove around 80 bpm with mellow piano, "
        "soft brushed drums, warm bass and light strings. Hopeful, cozy, companionship, late night desk. Mixed quietly to sit under voice-over."),
    "cueC_end": (int(C_END - B_END + 2),
        "Gentle uplifting cinematic lo-fi piano with soft strings and light brushed drums around 80 bpm, slightly brighter and more confident, "
        "then in the last twelve seconds the drums drop out and it resolves into a slow warm sustained final piano chord with string swell and a long fade. No vocals."),
}
SFX = {
    "room_night": "quiet apartment room tone at night, distant city traffic hum, very soft, steady, no voices",
    "door_unlock": "apartment front door lock turning with a key and the door opening slowly, close perspective, realistic foley",
    "chime_cold": "short cold synthetic notification chime from a smart speaker, two flat electronic tones, clean, no music",
    "error_beep": "short dull electronic error tone from a smart speaker, low descending two-note beep",
    "lamp_click": "single click of a desk lamp switch turning on, close, crisp, realistic foley",
    "keys": "a bunch of house keys gently dropped into a small ceramic dish, realistic foley, close",
    "soft_chime": "very soft warm gentle notification tone, a single rounded glassy note with a short airy tail, friendly",
    "light_off": "a wall light switch flicked off in a quiet living room, realistic foley",
    "curtain": "motorized curtain track closing slowly, soft electric motor hum and fabric sliding, indoor, realistic",
    "birds": "early morning ambience outside a window, a few gentle birds chirping, soft distant city, calm",
    "typing": "a few quick soft taps on a laptop keyboard, quiet, close, realistic",
    "switch": "soft airy whoosh with a gentle shimmering sparkle, short magical transition sound, subtle",
}


def hf(*args):
    r = subprocess.run([*HF, *args], capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=900)
    if r.returncode: raise RuntimeError(r.stderr or r.stdout)
    return r.stdout


def main():
    mode, only = sys.argv[1], set(sys.argv[2:])
    total = 0.0
    jobs = [("music", k, ["sonilo_music", "--prompt", p, "--duration", str(d)]) for k, (d, p) in MUSIC.items()]
    jobs += [("sfx", k, ["seed_audio", "--prompt", p, "--sample_rate", "48000"]) for k, p in SFX.items()]
    for kind, name, args in jobs:
        if only and name not in only: continue
        if mode == "cost":
            c = float(re.findall(r"[\d.]+", hf("generate", "cost", *args))[0]); total += c
            print(f"{kind:5s} {name:12s} {c:5.2f}"); continue
        d = os.path.join(ROOT, "audio", kind); os.makedirs(d, exist_ok=True)
        job = json.loads(hf("generate", "create", *args, "--wait", "--wait-timeout", "15m", "--json"))[0]
        ext = os.path.splitext(job["result_url"].split("?")[0])[1] or ".wav"
        urllib.request.urlretrieve(job["result_url"], os.path.join(d, name + ext))
        print("ok", kind, name, ext, flush=True)
    if mode == "cost": print(f"TOTAL {total:.2f}")


if __name__ == "__main__":
    main()
