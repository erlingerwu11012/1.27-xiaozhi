"""Voice-first timeline: shot lengths come from the real VO durations.

python timeline.py  ->  timeline.json  (shots with start/end frames, line cue times, captions, sfx cues)
Every downstream step (Blender shot renders, overlay compositor, music/SFX mixer) reads timeline.json.
"""
import json, os, wave

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
VO = os.path.join(PROJ, "audio", "vo")
FPS = 30

lines = {l["id"]: l for l in json.load(open(os.path.join(HERE, "lines.json"), encoding="utf-8"))["lines"]}


def dur(lid):
    p = os.path.join(VO, lid + ".wav")
    with wave.open(p) as w:
        return w.getnframes() / w.getframerate()


# Shot plan. Each item: id, kind (3d | plate | card), min length, lines as (line_id, gap_before_s), tail pad, and visual/caption info.
# 'src' = what is on screen; captions are rendered by the compositor.
PLAN = [
    dict(id="S01", kind="3d", lead=0.8, lines=[("L01", 0)], tail=0.6, act=1, letterbox=0),
    dict(id="S02", kind="card", min=1.6, lines=[], act=1, letterbox=1, title_small="念念不忘，必有回响"),
    dict(id="S03", kind="plate", src="pain-01-entry", lead=0.3, lines=[("L02", 0)], tail=0.4, act=2, letterbox=1, sfx=[("door_unlock", 0.0)]),
    dict(id="S04a", kind="plate", src="pain-02-speaker", lead=0.05, lines=[("L03", 0), ("L04", 0.1)], tail=0.15, act=2, letterbox=1, tag="没温度", sfx=[("chime_cold", "L04-0.2")]),
    dict(id="S04b", kind="plate", src="pain-02-speaker", min=1.2, lines=[], act=2, letterbox=1, tag="不主动", tag_sub="你不开口，它就一直沉默", grade="desat"),
    dict(id="S04c", kind="plate", src="pain-02-speaker", lead=0.05, lines=[("L05", 0), ("L06", 0.1)], tail=0.2, act=2, letterbox=1, tag="记不住", sfx=[("error_beep", "L06-0.15")]),
    dict(id="S05", kind="plate", src="pain-03-room", lead=0.3, lines=[("L07", 0)], tail=0.6, act=2, letterbox=1, tags_all=True),
    dict(id="S06", kind="plate", src="S06-alone-window", lead=0.4, lines=[("L08", 0), ("L09", 0.35)], tail=1.6, act=2, letterbox=1, big="缺少的，是陪伴"),
    dict(id="S07", kind="card", lead=0.9, lines=[("L10", 0)], tail=0.7, act=3, letterbox=1, whisper="你好，小念"),
    dict(id="S08", kind="3d", min=3.6, lines=[], act=3, letterbox=1, sfx=[("boot", 0.2)]),
    dict(id="S09", kind="3d", lead=1.6, lines=[("L11", 0)], tail=1.8, act=3, letterbox="open", sfx=[("lamp_click", 0.9)]),
    dict(id="S10", kind="3d", min=3.8, lines=[], act=3, title="念念不忘，必有回响", title_sub="你的桌面 AI 伙伴"),
    dict(id="S11", kind="plate", src="S11-keys-hand", min=2.4, lines=[], act=4, sfx=[("keys", 0.5)]),
    dict(id="S12", kind="3d", lead=0.6, lines=[("L12", 0)], tail=1.2, act=4, chapter=("01", "主动交互", "你走近，它先开口"), sense_ring=True, sfx=[("soft_chime", "L12-0.35")]),
    dict(id="S13", kind="3d", lead=0.3, lines=[("L13", 0), ("L14", 0.45)], tail=0.8, act=4, chapter=("02", "自然对话", "听得出情绪，也接得住话"), dialog=True),
    dict(id="S14", kind="3d", lead=0.2, lines=[("L15", 0)], tail=0.2, act=4, dialog=True),
    dict(id="S15", kind="3d+plate", src="S15-livingroom", lead=0.2, lines=[("L16", 0)], tail=0.9, act=4, chapter=("03", "接入 Home Assistant", "一句话，照顾全屋"), dialog=True, sfx=[("light_off", "L16+2.9"), ("curtain", "L16+3.3")]),
    dict(id="S16", kind="3d", lead=0.4, lines=[("L17", 0)], tail=0.6, act=4, corner="此前", dialog=True),
    dict(id="S17", kind="3d", lead=0.9, lines=[("L18", 0)], tail=1.0, act=4, corner="周三 · 早上", chapter=("04", "永久记忆", "跨越每一次对话，记得你在意的事"), dialog=True, sfx=[("birds", 0.0)]),
    dict(id="S18", kind="3d", lead=0.5, lines=[("L19", 0)], tail=1.4, act=4, feature="自定义唤醒词", card="wake", sfx=[("typing", "L19+0.3")]),
    dict(id="S19", kind="3d", lead=1.0, lines=[("L20", 0)], tail=1.0, act=4, feature="自定义角色形象与音色", corner_r="演示形象", sfx=[("switch", 0.45)]),
    dict(id="S20", kind="3d", lead=0.4, lines=[("L21", 0)], tail=1.2, act=4, feature="自定义 API", diagram=True),
    dict(id="S21", kind="3d", lead=0.6, lines=[("L22", 0), ("L23", 0.5)], tail=1.0, act=5, dialog=True, sfx=[("lamp_click", "L22+1.6")]),
    dict(id="S22", kind="3d", lead=0.6, lines=[("L24", 0), ("L25", 0.25)], tail=3.2, act=5, end_title=True),
]


def build():
    t = 0.0
    shots, cues = [], []
    for s in PLAN:
        start = t
        cur = start + s.get("lead", 0.0)
        lc = []
        for lid, gap in s["lines"]:
            cur += gap
            d = dur(lid)
            lc.append(dict(id=lid, who=lines[lid]["who"], text=lines[lid]["text"], start=round(cur, 3), end=round(cur + d, 3)))
            cur += d
        end = cur + s.get("tail", 0.0)
        end = max(end, start + s.get("min", 0.0))
        # snap to frames
        sf, ef = round(start * FPS), round(end * FPS)
        sfx = []
        for name, at in s.get("sfx", []):
            if isinstance(at, str):          # relative to a line: "L04-0.2" / "L16+1.2"
                lid, sign, off = at[:3], at[3], float(at[4:])
                base = next(c["start"] for c in lc if c["id"] == lid)
                at_t = base + (off if sign == "+" else -off)
            else:
                at_t = start + at
            sfx.append(dict(name=name, t=round(at_t, 3)))
        info = {k: v for k, v in s.items() if k not in ("lines", "lead", "tail", "min", "sfx")}
        shots.append(dict(**info, start=sf / FPS, end=ef / FPS, start_f=sf, end_f=ef, frames=ef - sf, lines=lc, sfx=sfx))
        cues += lc
        t = ef / FPS
    tl = dict(fps=FPS, duration=t, frames=round(t * FPS), shots=shots, vo=cues)
    json.dump(tl, open(os.path.join(HERE, "timeline.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return tl


if __name__ == "__main__":
    tl = build()
    for s in tl["shots"]:
        m, sec = divmod(s["start"], 60)
        print(f'{s["id"]:5s} {int(m)}:{sec:05.2f}  {s["end"] - s["start"]:5.2f}s  ' + " / ".join(l["text"] for l in s["lines"]))
    print(f'TOTAL {tl["duration"]:.2f}s  ({tl["frames"]} frames)')
