#!/usr/bin/env python3
"""Compare {placeholder} sets across locale files for the same key.

A key whose English text has {count} but whose Chinese text lost it will render a
literal `{count}` or silently drop the number. Works on TS/JS object-literal locale
files (`"key": "value"` / `'key': 'value'`) and on JSON.

Usage: python pr-work/_tools/locale_placeholders.py <dir> --base en.ts --others zh.ts,zh-TW.ts,jp.ts,kr.ts
"""
import json
import os
import re
import sys

ENTRY = re.compile(
    r"""^\s*(?:"([^"]+)"|'([^']+)')\s*:\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`([^`]*)`)""",
    re.M,
)
PH = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    out = {}
    for m in ENTRY.finditer(txt):
        key = m.group(1) or m.group(2)
        val = next(g for g in (m.group(3), m.group(4), m.group(5)) if g is not None)
        out[key] = val
    if not out:
        try:
            data = json.loads(txt)
            out = {k: v for k, v in data.items() if isinstance(v, str)}
        except Exception:
            pass
    return out


def compare(base, other):
    """[(key, missing_placeholders, extra_placeholders)] for keys both files define."""
    diffs = []
    for k, v in base.items():
        if k not in other:
            continue
        bp, op = set(PH.findall(v)), set(PH.findall(other[k]))
        if bp != op:
            diffs.append((k, sorted(bp - op), sorted(op - bp)))
    return diffs


def selftest():
    """A dropped `{count}` is reported; a key only one file has, or one whose
    placeholders merely reorder, is not."""
    import tempfile

    d = tempfile.mkdtemp(prefix="loc_")
    with open(os.path.join(d, "en.ts"), "w", encoding="utf-8", newline="\n") as f:
        f.write('export default {\n  "rows": "{count} rows",\n  "name": "Hi {who}",\n'
                '  "only.en": "{x}"\n};\n')
    with open(os.path.join(d, "zh.ts"), "w", encoding="utf-8", newline="\n") as f:
        f.write('export default {\n  "rows": "共 行",\n  "name": "{who}你好",\n};\n')
    diffs = compare(load(os.path.join(d, "en.ts")), load(os.path.join(d, "zh.ts")))
    assert diffs == [("rows", ["count"], [])], diffs
    print(f"selftest ok  diffs={diffs}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    d = sys.argv[1]
    base = os.path.join(d, sys.argv[sys.argv.index("--base") + 1])
    others = sys.argv[sys.argv.index("--others") + 1].split(",")
    b = load(base)
    print(f"base {os.path.basename(base)}: {len(b)} keys")
    total = 0
    for o in others:
        p = os.path.join(d, o)
        if not os.path.exists(p):
            print(f"  {o}: missing")
            continue
        diffs = compare(b, load(p))
        total += len(diffs)
        print(f"  {o}: {len(diffs)} placeholder mismatches")
        for k, miss, extra in diffs[:10]:
            print(f"     {k}  missing={miss} extra={extra}")
    print(f"total mismatches: {total}")


if __name__ == "__main__":
    main()
