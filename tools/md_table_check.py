#!/usr/bin/env python3
"""Report markdown table rows whose cell count differs from the header row.

A mismatched row renders as a broken table on the docs site, so this is a real
defect class that link checkers do not catch.

Usage: python pr-work/_tools/md_table_check.py <docs_root> [--max 20]
"""
import glob
import os
import re
import sys

SPLIT = re.compile(r"(?<!\\)\|")


def cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return SPLIT.split(s)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    root = sys.argv[1].rstrip("/\\")
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 20

    bad = []
    files = [p for p in glob.glob(os.path.join(root, "**", "*.md*"), recursive=True)]
    for p in files:
        try:
            lines = open(p, encoding="utf-8", errors="replace").read().split("\n")
        except OSError:
            continue
        in_code, i = False, 0
        while i < len(lines):
            l = lines[i].strip()
            if l.startswith("```"):
                in_code = not in_code
                i += 1
                continue
            if in_code or not l.startswith("|"):
                i += 1
                continue
            width = len(cells(l))
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                row = lines[j].strip()
                n = len(cells(row))
                if n != width:
                    bad.append((os.path.relpath(p, root), j + 1, width, n, row[:80]))
                j += 1
            i = j

    print(f"files={len(files)}  mismatched-rows={len(bad)}")
    for src, ln, w, n, row in bad[:cap]:
        print(f"   {src}:{ln}  header={w} row={n}  {row}")


if __name__ == "__main__":
    main()
