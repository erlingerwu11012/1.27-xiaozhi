#!/usr/bin/env bash
# Download the full Noto Sans SC / Noto Serif SC TTFs (SIL Open Font License)
# from Google Fonts into source/fonts/full/. Needed only to re-subset fonts.
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)/fonts/full"
mkdir -p "$dir"
css=$(curl -sS -A "curl/8" "https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@500;600;700")
python3 - "$dir" <<PY
import re, subprocess, sys
css = """$css"""
for fam, w, url in re.findall(r"font-family: '([^']+)';\s*font-style: normal;\s*font-weight: (\d+);.*?src: url\(([^)]+)\)", css, re.S):
    out = f"{sys.argv[1]}/{fam.replace(' ', '')}-{w}.ttf"
    subprocess.run(["curl", "-sS", "-o", out, url], check=True)
    print("saved", out)
PY
