"""Transcribe every VO clip with Higgsfield speech2text and compare with the script (AI can't listen)."""
import json, os, subprocess
from synth_voices import HF, OUT, HERE
cfg = json.load(open(os.path.join(HERE, "..", "lines.json"), encoding="utf-8"))
res = {}
for ln in cfg["lines"]:
    p = os.path.join(OUT, ln["id"] + ".wav")
    r = subprocess.run([*HF, "generate", "create", "speech2text", "--audio-references", p, "--wait", "--json"],
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=300)
    job = json.loads(r.stdout)[0]
    res[ln["id"]] = {"script": ln["text"], "heard": job["result_json"]["text"], "vtt": job["result_json"].get("vtt")}
    print(ln["id"], "|", ln["text"], "|", job["result_json"]["text"], flush=True)
json.dump(res, open(os.path.join(OUT, "transcripts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
