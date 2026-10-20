"""Build a scoped patch from fresh production source (no private config)."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parent


def remove_function(source, name):
    tree = ast.parse(source)
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(nodes) == 1, name
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    return "".join(lines[:node.lineno - 1] + lines[node.end_lineno:])


changes = {}
source = (ROOT / "before/core/connection.py").read_text(encoding="utf-8")
source = source.replace("from core.utils.prompt_pipeline import finalization_mode, is_pipeline_v2", "from core.utils.prompt_pipeline import is_pipeline_v2")
start = source.index("            # 二次表达改写仅作为 legacy_two_pass")
end = source.index("        if depth == 0:\n            self.enqueue_tts(", start)
direct = source[source.index("                self.dialogue.put(\n", start):end]
direct = "".join(line[4:] if line.startswith("    ") else line for line in direct.splitlines(keepends=True))
source = source[:start] + "            # 主模型定稿直接进入 TTS，不再调用第二次模型改写。\n" + direct + source[end:]
source = remove_function(source, "_run_expressive_final")
assert "_run_expressive_final" not in source and "finalization_mode" not in source
changes["core/connection.py"] = ("before/core/connection.py", source)

source = (ROOT / "before/core/prompt_pipeline.py").read_text(encoding="utf-8")
source = source.replace("- speech_expression: { mode, finalization }", "- speech_expression: { mode }  # 旧 finalization 字段忽略，不再有二次润色")
source = remove_function(source, "finalization_mode")
changes["core/utils/prompt_pipeline.py"] = ("before/core/prompt_pipeline.py", source)

source = (ROOT / "before/test_prompt_pipeline_v2.py").read_text(encoding="utf-8")
source = remove_function(source, "test_finalization_default_legacy")
needle = "    def test_include_stream_usage_default_false(self):"
source = source.replace(needle, "    def test_two_pass_finalization_switch_removed(self):\n        self.assertFalse(hasattr(prompt_pipeline, 'finalization_mode'))\n\n" + needle)
changes["test/test_prompt_pipeline_v2.py"] = ("before/test_prompt_pipeline_v2.py", source)

source = (ROOT / "before/test_official_dialogue.py").read_text(encoding="utf-8")
source = source.replace("Official dialogue extras: tool-free final expression and no ASR emotion inject.", "Official dialogue: primary answer tags and captions remain supported.")
source = source.replace("from core.providers.tts.official.prompt import EXPRESSIVE_STAGE_NOTICE, OFFICIAL_EXPRESSION_CONSTRAINT", "from core.providers.tts.official.prompt import OFFICIAL_EXPRESSION_CONSTRAINT")
source = source.replace("from unittest.mock import MagicMock\n", "")
source = remove_function(source, "test_expressive_stage_forbids_tools")
source = remove_function(source, "test_expressive_call_counter")
changes["test/test_official_dialogue.py"] = ("before/test_official_dialogue.py", source)

manifest, patches = {}, []
for name, (before, source) in changes.items():
    ast.parse(source)
    target = ROOT / "delivery" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    old = (ROOT / before).read_bytes()
    newline = b"\r\n" if b"\r\n" in old else b"\n"
    target.write_bytes(source.encode("utf-8").replace(b"\n", newline))
    manifest[name] = {"before_sha256": hashlib.sha256(old).hexdigest(), "after_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    patches.extend(difflib.unified_diff(old.decode().replace("\r\n", "\n").splitlines(True), source.splitlines(True), fromfile="a/main/xiaozhi-server/" + name, tofile="b/main/xiaozhi-server/" + name))
(ROOT / "source.patch").write_text("".join(patches), encoding="utf-8", newline="\n")
(ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"changed": list(manifest), "removed_method": True}, ensure_ascii=False))
