"""Voice-first step: synthesize every line in lines.json via Higgsfield TTS.

Usage:
  python synth_voices.py cost  [ids...]   # report estimated credits only
  python synth_voices.py make  [ids...]   # generate (skips lines already on disk)
Output: ../../audio/vo/<id>.wav  +  ../../audio/vo/manifest.json
"""
import json, os, re, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "audio", "vo")
HF_JS = os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "@higgsfield", "cli", "bin", "higgsfield.js")
HF = ["node", HF_JS] if os.name == "nt" else ["higgsfield"]

def hf(*args):
    r = subprocess.run([*HF, *args], capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=300)
    if r.returncode: raise RuntimeError(r.stderr or r.stdout)
    return r.stdout

def main():
    mode, ids = sys.argv[1], set(sys.argv[2:])
    cfg = json.load(open(os.path.join(HERE, "..", "lines.json"), encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    man_path = os.path.join(OUT, "manifest.json")
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    total = 0.0
    for ln in cfg["lines"]:
        if ids and ln["id"] not in ids: continue
        v = cfg["voices"][ln["who"]]
        args = [v["model"], "--prompt", ln["text"], "--voice", v["voice"]]
        dst = os.path.join(OUT, ln["id"] + ".wav")
        if mode == "cost":
            c = float(re.findall(r"[\d.]+", hf("generate", "cost", *args))[0]); total += c
            print(f'{ln["id"]} {c:5.2f}  {ln["text"]}')
            continue
        if os.path.exists(dst) and man.get(ln["id"], {}).get("text") == ln["text"]:
            print("skip", ln["id"]); continue
        job = json.loads(hf("generate", "create", *args, "--wait", "--json"))[0]
        urllib.request.urlretrieve(job["result_url"], dst)
        man[ln["id"]] = {"text": ln["text"], "who": ln["who"], "voice": v["voice"], "job": job["id"], "url": job["result_url"]}
        json.dump(man, open(man_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("ok", ln["id"], ln["text"])
    if mode == "cost": print(f"TOTAL {total:.2f} credits")

if __name__ == "__main__":
    main()
