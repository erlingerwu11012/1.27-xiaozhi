"""Apply the approved 100,000-token summary trigger without changing its algorithm.

Runs against an explicitly selected server config. Records contain only the
compression settings and file hashes; complete configs are never exported.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

import yaml

TARGET_BUDGET = 125000
TARGET_RATIO = 0.8
SETTING_KEYS = ("enabled", "max_context_tokens", "compact_threshold",
                "keep_recent_rounds", "max_summary_chars")


def prepare(raw):
    text = raw.decode("utf-8")
    before = yaml.safe_load(text)
    section = before.get("context_compress")
    if not isinstance(section, dict):
        raise ValueError("missing_compression_section")
    if section.get("max_context_tokens") != 4000 or section.get("compact_threshold") != 0.75:
        raise ValueError("unexpected_existing_threshold")
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if re.match(r"^context_compress:\s*(?:#.*)?$", line.rstrip("\r\n"))]
    if len(starts) != 1:
        raise ValueError("ambiguous_compression_section")
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i][0].isspace()
                and not lines[i].startswith("#")), len(lines))
    for key, value in (("max_context_tokens", "125000"), ("compact_threshold", "0.8")):
        matches = [i for i in range(start + 1, end)
                   if re.match(r"^[ \t]+" + key + r":", lines[i])]
        if len(matches) != 1:
            raise ValueError("ambiguous_compression_setting")
        i = matches[0]
        lines[i], count = re.subn(
            r"^([ \t]+" + key + r":[ \t]*)([^#\r\n]*?)([ \t]*(?:#[^\r\n]*)?)(\r?\n|$)",
            lambda m: m.group(1) + value + m.group(3) + m.group(4), lines[i])
        if count != 1:
            raise ValueError("unsupported_setting_line")
    updated = "".join(lines).encode("utf-8")
    after = yaml.safe_load(updated)
    expected = copy.deepcopy(before)
    expected["context_compress"]["max_context_tokens"] = TARGET_BUDGET
    expected["context_compress"]["compact_threshold"] = TARGET_RATIO
    if after != expected:
        raise ValueError("unrelated_configuration_changed")
    if int(TARGET_BUDGET * TARGET_RATIO) != 100000:
        raise ValueError("incorrect_trigger")
    record = {"before_sha": hashlib.sha256(raw).hexdigest(),
              "after_sha": hashlib.sha256(updated).hexdigest(),
              "before": {k: section.get(k) for k in SETTING_KEYS},
              "after": {k: after["context_compress"].get(k) for k in SETTING_KEYS},
              "actual_summary_trigger": 100000}
    return updated, record


def verify_dialogue(root, section):
    """Exercise the real Dialogue class with synthetic messages and a fake LLM."""
    import sys
    from unittest.mock import MagicMock, patch
    sys.path.insert(0, str(root))
    with patch("config.logger.setup_logging", return_value=MagicMock()):
        from core.utils.dialogue import Dialogue, Message
    checked = 0
    for total, calls in ((99999, 0), (100000, 1), (100001, 1)):
        dialogue = Dialogue()
        dialogue.configure_compact({"context_compress": section})
        assert dialogue.compact_enabled
        assert int(dialogue.max_context_tokens * dialogue.compact_threshold) == 100000
        assert dialogue.keep_recent_rounds == 4 and dialogue.max_summary_chars == 500
        dialogue.put(Message(role="system", content="Synthetic role instructions."))
        for i in range(10):
            dialogue.put(Message(role="user", content=f"Synthetic question {i}."))
            dialogue.put(Message(role="assistant", content=f"Synthetic reply {i}."))
        llm = MagicMock()
        llm.response_no_stream.return_value = "Synthetic summary preserves the test topic and pending work."
        with patch.object(dialogue, "_estimate_total_tokens", side_effect=[total, 10000]):
            dialogue.check_and_compact(llm)
        assert llm.response_no_stream.call_count == calls
        if calls:
            assert len([m for m in dialogue.dialogue if m.role == "user"]) == 4
            assert dialogue.compact_summary == llm.response_no_stream.return_value
        else:
            assert len(dialogue.dialogue) == 21 and not dialogue.compact_summary
        checked += 1
    return {"synthetic_boundary_cases_passed": checked, "upstream_calls": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-sha")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--record", type=Path)
    args = parser.parse_args()
    path = args.config.resolve(strict=True)
    raw = path.read_bytes()
    updated, record = prepare(raw)
    if args.expected_sha and record["before_sha"] != args.expected_sha:
        raise ValueError("configuration_changed_since_review")
    record["tests"] = verify_dialogue(path.parent, yaml.safe_load(updated)["context_compress"])
    record["applied"] = False
    if args.apply:
        if path.read_bytes() != raw:
            raise ValueError("configuration_changed_during_tests")
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, temporary = tempfile.mkstemp(prefix=".context-threshold-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(updated)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        record["applied"] = True
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        os.chmod(args.record, 0o600)
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
