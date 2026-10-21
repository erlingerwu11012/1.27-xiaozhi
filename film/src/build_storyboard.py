"""Build the review page (storyboard/index.html) and the timecode table in storyboard_v2.md from timeline.json.

python build_storyboard.py
"""
import html, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
TL = json.load(open(os.path.join(HERE, "timeline.json"), encoding="utf-8"))

ACTS = {1: "第一幕 · 发问", 2: "第二幕 · 痛点", 3: "第三幕 · 回响登场", 4: "第四幕 · 回响的方式", 5: "第五幕 · 收尾"}
WHO = {"N": "旁白（男）", "U": "你（男）", "X": "小念（女）", "X2": "小念 · 新音色（女）", "D": "某智能设备"}
SRC = {"3d": "Blender · 真实 CAD", "plate": "Higgsfield 底片", "card": "图形卡", "3d+plate": "Blender → Higgsfield 底片"}

PIC = {
    "S01": "深夜电脑桌远景，屏幕未亮，产品隐在暗处；镜头极慢推近",
    "S02": "画面压暗，遮幅合拢成 2.39:1，宣传语小字一闪而过",
    "S03": "门缝透进走廊的光，屋里一片暗（复用 v1 底片）",
    "S04a": "某智能设备特写，冷白光环亮起，答非所问",
    "S04b": "同一机位推近、去色，光环熄灭，它一直沉默",
    "S04c": "光环再亮，问它上周的事，它记不得",
    "S05": "空荡的公寓全景，三个标签收拢",
    "S06": "窗边的背影，城市夜景；镜头后拉，人越来越小，停在大字上",
    "S07": "全黑。一声轻语，画面中央浮现唤醒词",
    "S08": "近景：屏幕亮起，原开机动画的光照亮白色前盖倒角和齿纹旋钮",
    "S09": "从近景拉开成三分之四中景；原壁纸和 Spine 角色亮起，台灯随后亮起，遮幅打开",
    "S10": "产品偏右，左侧主标题",
    "S11": "傍晚的玄关，一只手放下钥匙（只拍手）",
    "S12": "桌搭中景，产品前方一圈淡淡的感应光扫过（功能示意）",
    "S13": "坐在桌前的视角，显示器和产品同框，对话逐句出现",
    "S14": "台灯、显示器、产品同框的桌面全景，暖光",
    "S15": "桌面台灯渐暗（Blender），随后切到客厅：主灯熄灭、窗帘合上（Higgsfield 底片，开灯/关灯交叉淡化）",
    "S16": "夜晚，台灯低档，产品近景；角标「此前」",
    "S17": "同一张桌子换成清晨的光，角标「周三 · 早上」",
    "S18": "产品侧面中景，设置卡片里的唤醒词被改写成别的名字后又改回",
    "S19": "产品正面近景，屏幕内容整体淡出淡入，换成演示形象和新壁纸",
    "S20": "产品背面三分之四，慢速环绕；右侧线条图逐级展开",
    "S21": "深夜桌面全景，台灯最暗档，只剩屏幕里的角色在微动；镜头拉远",
    "S22": "产品居中靠下，宣传语和功能清单逐行浮现，淡出",
}
MUSIC = {1: "低频长音铺底", 2: "冷色氛围，S06 末尾完全静默", 3: "钢琴单音 → 温暖和弦铺开 → 主旋律进入", 4: "温暖 lo-fi 钢琴 + 弦乐，人声出现时自动避让", 5: "收束，最后一个和弦"}
SFX = {"door_unlock": "门锁/钥匙", "chime_cold": "机械提示音", "error_beep": "错误提示音", "boot": "原 boot.ogg", "lamp_click": "台灯开关",
       "keys": "钥匙落盘", "soft_chime": "轻柔提示音", "light_off": "关灯", "curtain": "窗帘电机", "birds": "鸟鸣", "typing": "打字", "switch": "切换音"}


def tc(t):
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:05.2f}"


def captions(s):
    out = []
    if s.get("chapter"): out.append(f'章节 {s["chapter"][0]} {s["chapter"][1]}：{s["chapter"][2]}')
    for k, label in (("tag", "标签"), ("big", "大字"), ("whisper", "字"), ("title_small", "小字"), ("corner", "角标"), ("corner_r", "角标"), ("feature", "卖点")):
        if s.get(k): out.append(f"{label}：{s[k]}")
    if s.get("tags_all"): out.append("不主动 · 没温度 · 记不住")
    if s.get("title"): out.append(f'主标题：{s["title"]} / {s.get("title_sub", "")}')
    if s.get("diagram"): out.append("线条图：自制硬件主板 → 云端 Harness → 大模型 / ASR / TTS；自定义 API")
    if s.get("end_title"): out.append("念念不忘，必有回响 ｜ 6 项功能 ｜「你好，小念」")
    return out


def md_table():
    rows = ["| 镜头 | 时间码 | 时长 | 画面 | 来源 | 台词 | 字幕/图形 | 音效 |", "|---|---|---|---|---|---|---|---|"]
    for s in TL["shots"]:
        lines = "<br>".join(f'{WHO[l["who"]]}：{l["text"]}' for l in s["lines"]) or "—"
        rows.append(f'| {s["id"]} | {tc(s["start"])}–{tc(s["end"])} | {s["end"] - s["start"]:.1f}s | {PIC[s["id"]]} | {SRC[s["kind"]]} | {lines} | {"；".join(captions(s)) or "—"} | {"、".join(SFX[x["name"]] for x in s["sfx"]) or "—"} |')
    return "\n".join(rows)


def update_md():
    p = os.path.join(PROJ, "storyboard_v2.md")
    s = open(p, encoding="utf-8").read()
    block = f"<!-- TIMECODES:BEGIN -->\n## 成片时间码（按配音实测，自动生成）\n\n全片 {tc(TL['duration'])}，{TL['frames']} 帧 @30fps。\n\n{md_table()}\n<!-- TIMECODES:END -->"
    if "<!-- TIMECODES:BEGIN -->" in s:
        s = re.sub(r"<!-- TIMECODES:BEGIN -->.*<!-- TIMECODES:END -->", block, s, flags=re.S)
    else:
        s = s.replace("\n## 全部台词（配音脚本）", "\n" + block + "\n\n## 全部台词（配音脚本）")
    open(p, "w", encoding="utf-8").write(s)


def page():
    e = html.escape
    shots_html, act = [], None
    for s in TL["shots"]:
        if s["act"] != act:
            act = s["act"]
            shots_html.append(f'<h2 class="act"><span>{e(ACTS[act])}</span><em>音乐：{e(MUSIC[act])}</em></h2>')
        lines = "".join(f'<li class="w-{l["who"]}"><b>{e(WHO[l["who"]])}</b><span>{e(l["text"])}</span><i>{tc(l["start"])}</i></li>' for l in s["lines"])
        caps = "".join(f"<li>{e(c)}</li>" for c in captions(s))
        sfx = "、".join(SFX[x["name"]] for x in s["sfx"])
        shots_html.append(f'''<article class="shot" id="{s["id"]}">
  <figure><img src="web/{s["id"]}.jpg" alt="{s["id"]} 关键帧" loading="lazy" width="1280" height="720"></figure>
  <div class="meta">
    <header><strong>{s["id"]}</strong><span class="tc">{tc(s["start"])} – {tc(s["end"])}</span><span class="dur">{s["end"] - s["start"]:.1f}s</span><span class="src src-{s["kind"].replace("+", "")}">{e(SRC[s["kind"]])}</span></header>
    <p class="pic">{e(PIC[s["id"]])}</p>
    {f'<ul class="lines">{lines}</ul>' if lines else ''}
    {f'<ul class="caps">{caps}</ul>' if caps else ''}
    {f'<p class="sfx">音效：{e(sfx)}</p>' if sfx else ''}
  </div>
</article>''')
    tpl = open(os.path.join(HERE, "storyboard_template.html"), encoding="utf-8").read()
    out = tpl.replace("{{SHOTS}}", "\n".join(shots_html)).replace("{{DURATION}}", tc(TL["duration"])).replace("{{NSHOTS}}", str(len(TL["shots"])))
    open(os.path.join(PROJ, "storyboard", "index.html"), "w", encoding="utf-8").write(out)


if __name__ == "__main__":
    update_md(); page(); print("ok")
