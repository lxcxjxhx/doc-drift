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


def main():
    root = Path(sys.argv[1])
    show = "--show" in sys.argv
    total = drift = 0
    for base_file in sorted((root / BASE).glob("*.json")):
        try:
            base = dict(flat(json.loads(base_file.read_text(encoding="utf-8"))))
        except json.JSONDecodeError as e:
            print(f"! {base_file.name}: {e}")
            continue
        for other in OTHERS:
            f = root / other / base_file.name
            if not f.exists():
                print(f"! missing {other}/{base_file.name}")
                continue
            try:
                tr = dict(flat(json.loads(f.read_text(encoding="utf-8"))))
            except json.JSONDecodeError as e:
                print(f"! {other}/{base_file.name}: {e}")
                continue
            for key, text in base.items():
                want = set(PH.findall(text))
                if not want:
                    continue
                total += 1
                got = set(PH.findall(tr.get(key, "")))
                if got != want:
                    drift += 1
                    if show:
                        print(f"{other}/{base_file.name}  {key}  "
                              f"missing={sorted(want - got)} extra={sorted(got - want)}")
    print(f"checked {total} interpolated keys; placeholder drift={drift}")


if __name__ == "__main__":
    main()
