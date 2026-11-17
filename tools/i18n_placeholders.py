#!/usr/bin/env python3
"""Compare {placeholder} sets per key between FastGPT locale JSON files.

A key whose English text has {count} but whose translation lost it renders a
literal `{count}` (or drops the number). Keys missing from a translation are a
different defect class and are reported separately, not mixed in here.

usage: python pr-work/_tools/i18n_placeholders.py <i18n_dir> [--show]
"""
import json
import re
import sys
from pathlib import Path

PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
BASE = "en"
OTHERS = ["zh-CN", "zh-Hant", "ko-KR"]


def flat(d, prefix=""):
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from flat(v, key)
        elif isinstance(v, str):
            yield key, v


def scan(root, others=None):
    """Return (checked_keys, [(locale, file, key, missing, extra)])."""
    root = Path(root)
    others = OTHERS if others is None else others
    total, drift = 0, []
    for base_file in sorted((root / BASE).glob("*.json")):
        try:
            base = dict(flat(json.loads(base_file.read_text(encoding="utf-8"))))
        except json.JSONDecodeError:
            continue
        for other in others:
            f = root / other / base_file.name
            if not f.exists():
                continue
            try:
                tr = dict(flat(json.loads(f.read_text(encoding="utf-8"))))
            except json.JSONDecodeError:
                continue
            for key, text in base.items():
                want = set(PH.findall(text))
                if not want:
                    continue
                total += 1
                got = set(PH.findall(tr.get(key, "")))
                if got != want:
                    drift.append((other, base_file.name, key,
                                  sorted(want - got), sorted(got - want)))
    return total, drift


def selftest():
    """A key that lost a placeholder is reported; a key with none, and a nested key
    that kept its placeholder, are not."""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="i18n_"))
    (root / BASE).mkdir()
    (root / "zh-CN").mkdir()
    (root / BASE / "common.json").write_text(
        '{"rows": "{count} rows", "nested": {"who": "Hi {who}"}, "plain": "no placeholder"}',
        encoding="utf-8")
    (root / "zh-CN" / "common.json").write_text(
        '{"rows": "共 行", "nested": {"who": "{who}你好"}, "plain": "没有"}',
        encoding="utf-8")
    total, drift = scan(root, ["zh-CN"])
    assert total == 2, total
    assert [d[2:] for d in drift] == [("rows", ["count"], [])], drift
    print(f"selftest ok  checked={total} drift={[(d[2], d[3]) for d in drift]}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    root = Path(sys.argv[1])
    show = "--show" in sys.argv
    total, drift = scan(root)
    if show:
        for other, name, key, missing, extra in drift:
            print(f"{other}/{name}  {key}  missing={missing} extra={extra}")
    print(f"checked {total} interpolated keys; placeholder drift={len(drift)}")


if __name__ == "__main__":
    main()
