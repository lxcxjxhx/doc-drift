#!/usr/bin/env python3
"""Three docs dimensions that link/anchor/table checkers do not cover.

  fence  <root>   fenced code blocks with no language tag, judged against the
                  repo's OWN convention: only outliers inside a tree that is
                  otherwise consistent (>=98% tagged, >=50 blocks) are reported.
  dup    <root>   the same heading text repeated inside one file (GitHub then
                  generates `-1` suffixes, so `#slug` links become ambiguous).
  parity <repo>   localized page whose heading structure drifted from its
                  counterpart in the other language tree.
  struct <repo>   language-independent structure that translation never
                  removes: code blocks, tables, images, source-file links.
                  A zh page with 0 of what the en page has 8 of is missing a
                  whole section, not "translated differently".

Usage:
  python pr-work/_tools/md_lint.py fence  <docs_root> [--max 20]
  python pr-work/_tools/md_lint.py dup    <docs_root> [--max 20]
  python pr-work/_tools/md_lint.py parity <repo>      [--max 20]
  python pr-work/_tools/md_lint.py selftest
"""
import os
import re
import sys
import tempfile
from pathlib import Path

FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SKIP_DIRS = {".git", "node_modules", ".next", "public", ".venv", "venv", "__pycache__"}
# A changelog repeats `Added`/`Fixed` under every release heading by design.
CHANGELOG_LIKE = {"CHANGELOG.md", "CHANGELOG.mdx", "CHANGELOG.rst", "CHANGES.md", "HISTORY.md"}


def scan(path):
    """Return (fences, headings). fences = [(line, lang)], headings = [(line, level, text)].

    Fences: opening runs only. A closing run repeats the same char at >= length
    and carries no info string, which is how the state machine below tells them
    apart. Headings inside a fenced block are comments, not headings.
    """
    fences, heads = [], []
    openf = None
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return fences, heads
    for i, line in enumerate(text.split("\n"), 1):
        m = FENCE.match(line)
        if openf is None:
            if m:
                run, info = m.group(2), m.group(3).strip()
                openf = (run[0], len(run))
                fences.append((i, info.split()[0] if info else ""))
                continue
            h = HEADING.match(line)
            if h:
                heads.append((i, len(h.group(1)), h.group(2)))
        elif m and m.group(2)[0] == openf[0] and len(m.group(2)) >= openf[1] and not m.group(3).strip():
            openf = None
    return fences, heads


def walk(root):
    out = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in fs:
            if f.endswith((".md", ".mdx")):
                out.append(os.path.join(dp, f))
    return out


def locator(root):
    """Print path with the walked root stripped, so output is repo-relative."""
    return lambda p: os.path.relpath(p, root).replace(os.sep, "/")


def cmd_fence(root, cap):
    rel = locator(root)
    total = missing = 0
    out = []
    for p in walk(root):
        for line, lang in scan(p)[0]:
            total += 1
            if not lang:
                missing += 1
                out.append((rel(p), line))
    cover = 1 - missing / total if total else 1.0
    print(f"root={os.path.basename(root)}  fences={total}  untagged={missing}  tagged={cover:.3%}")
    if total < 50 or cover < 0.98:
        print("   note: convention not established (<50 blocks or <98% tagged): not a defect")
        return
    print(f"   -> repo convention is {cover:.2%} tagged; {missing} outlier(s):")
    for src, line in out[:cap]:
        print(f"   {src}:{line}")


def cmd_dup(root, cap):
    rel = locator(root)
    files = 0
    groups = []
    acknowledged = 0
    structural = 0
    for p in walk(root):
        name = os.path.basename(str(p))
        if name in CHANGELOG_LIKE:
            continue
        heads = scan(p)[1]
        seen = {}
        for line, lvl, text in heads:
            key = text.strip().lower()
            seen.setdefault(key, []).append((line, lvl))
        dups = {k: v for k, v in seen.items() if len(v) > 1}
        if not dups:
            continue
        # A file whose own links point at `#slug` and `#slug-1` has already made the
        # disambiguation explicit — GitHub's suffix is part of the document, not drift.
        text = Path(p).read_text(encoding="utf-8", errors="replace") if not isinstance(p, Path) \
            else p.read_text(encoding="utf-8", errors="replace")
        linked = set(re.findall(r"\]\(#([^)\s]+)\)", text))
        for k in list(dups):
            slug = re.sub(r"[^\w\- ]+", "", k).strip().lower().replace(" ", "-")
            numbered = {f"{slug}-{i}" for i in range(1, len(dups[k]))}
            if numbered and numbered <= linked:
                dups.pop(k)
                acknowledged += 1
                continue
            # The same sub-heading under *different* parents is a repeated structure, not
            # an ambiguous anchor: an ADR with one `#### Pros` per option, a changelog with
            # one `### Fixed` per release, a gallery with one `Key Requirements:` per entry.
            parents = {_parent_of(heads, line, lvl) for line, lvl in dups[k]}
            if len(parents) == len(dups[k]) and len(parents) > 1:
                dups.pop(k)
                structural += 1
        if dups:
            files += 1
            groups.append((rel(p), dups))
    n = sum(len(d) for _p, d in groups)
    print(f"root={rel(root) or '.'}  files-with-dup-heading={files}  dup-groups={n}  "
          f"acknowledged-by-anchor={acknowledged}  repeated-under-different-parents={structural}")
    for src, dups in groups[:cap]:
        for k, lines in list(dups.items())[:6]:
            print(f"   {src}  x{len(lines)}  {k!r}  lines={[ln for ln, _ in lines]}")


def _parent_of(heads, line, level):
    """Text of the nearest heading above `line` with a level lower than `level`."""
    parent = ""
    for h_line, h_level, h_text in heads:
        if h_line >= line:
            break
        if h_level < level:
            parent = h_text.strip().lower()
    return parent


def find_pair(repo):
    skip = {".git", "node_modules", "images", "assets", "img", "static", "public"}
    best = None
    for root, dirs, _ in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in skip]
        if root.count(os.sep) - repo.count(os.sep) > 3:
            dirs[:] = []
            continue
        for en, zh in (("en", "zh"), ("en", "zh-CN"), ("en-US", "zh-CN"), ("en", "zh_CN")):
            if en in dirs and zh in dirs:
                cand = (root, en, zh)
                if best is None or _weight(cand) > _weight(best):
                    best = cand
    return best


def _weight(cand):
    root, en, _zh = cand
    return sum(len(fs) for _d, _s, fs in os.walk(os.path.join(root, en)))


def cmd_parity(repo, cap):
    pair = find_pair(repo)
    if not pair:
        print("no locale pair found")
        return
    base, en, zh = pair
    files = []
    for lang_dir, other in ((en, zh), (zh, en)):
        root = os.path.join(base, lang_dir)
        for dp, dirs, fs in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in fs:
                if not f.endswith((".md", ".mdx")):
                    continue
                relp = os.path.relpath(os.path.join(dp, f), root)
                if os.path.exists(os.path.join(base, other, relp)):
                    files.append((lang_dir, relp))
    files = [f for f in files if f[0] == en]  # one pass, en side is the reference
    drift = []
    for _lang, relp in files:
        ep = os.path.join(base, en, relp)
        zp = os.path.join(base, zh, relp)
        eh, zh_h = scan(ep)[1], scan(zp)[1]
        el = [l for _n, l, _t in eh]
        zl = [l for _n, l, _t in zh_h]
        if el == zl:
            continue
        # first divergence: which heading is missing in zh
        first = next((i for i in range(min(len(el), len(zl))) if el[i] != zl[i]), min(len(el), len(zl)))
        drift.append((abs(len(el) - len(zl)), len(el), len(zl), relp,
                      (eh[first][2][:60] if first < len(eh) else "<eof>"),
                      (zh_h[first][2][:60] if first < len(zh_h) else "<eof>")))
    drift.sort(reverse=True)
    print(f"base={os.path.relpath(base, repo)}  pairs={len(files)}  heading-drift={len(drift)}")
    for d, ne, nz, relp, etxt, ztxt in drift[:cap]:
        print(f"   {relp}  en={ne} zh={nz} (Δ{d})\n      first-diff en={etxt!r} zh={ztxt!r}")


SRC_LINK = re.compile(r"\]\([^)\s]*\.(?:java|py|cc|cpp|cxx|c|h|hpp|kt|scala|go|rs|md)(?:#[^)\s]*)?\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(")
TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")


def counts(path):
    """Structural elements a translation normally keeps 1:1."""
    fences, heads = scan(path)
    n = {"fence": len(fences), "head": len(heads), "img": 0, "srclink": 0, "table": 0}
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().split("\n")
    except OSError:
        return n
    for line in lines:
        if IMAGE.search(line):
            n["img"] += IMAGE.findall(line).__len__()
        n["srclink"] += len(SRC_LINK.findall(line))
        if "|" in line and TABLE_SEP.match(line):
            n["table"] += 1
    return n


def cmd_struct(repo, cap):
    pair = find_pair(repo)
    if not pair:
        print("no locale pair found")
        return
    base, en, zh = pair
    pairs = []
    for dp, dirs, fs in os.walk(os.path.join(base, en)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in fs:
            if not f.endswith((".md", ".mdx")):
                continue
            relp = os.path.relpath(os.path.join(dp, f), os.path.join(base, en))
            if os.path.exists(os.path.join(base, zh, relp)):
                pairs.append(relp)
    rows = []
    for relp in pairs:
        a = counts(os.path.join(base, en, relp))
        b = counts(os.path.join(base, zh, relp))
        diffs = [(k, a[k], b[k]) for k in a if a[k] != b[k] and max(a[k], b[k]) >= 2]
        if diffs:
            rows.append((sum(abs(x - y) for _k, x, y in diffs), relp, diffs))
    rows.sort(reverse=True)
    print(f"base={os.path.relpath(base, repo)}  pairs={len(pairs)}  struct-drift={len(rows)}")
    for score, relp, diffs in rows[:cap]:
        d = "  ".join(f"{k}:en={x}/zh={y}" for k, x, y in diffs)
        print(f"   {relp}  (Δ{score})  {d}")


def selftest():
    """Known answers, not plausible output. Run this before trusting any report."""
    d = tempfile.mkdtemp(prefix="mdlint_")
    p = os.path.join(d, "a.md")
    open(p, "w", encoding="utf-8", newline="\n").write(
        "# Title\n"
        "\n"
        "```python\n"
        "# not a heading\n"
        "print(1)\n"
        "```\n"
        "\n"
        "```\n"
        "untagged\n"
        "```\n"
        "\n"
        "~~~rust\n"
        "let x = 1;\n"
        "~~~\n"
        "\n"
        "## Dup\n"
        "## Dup\n"
        "## Other\n"
        "```\n"
        "### still code\n"
        "```\n"
    )
    fences, heads = scan(p)
    assert [l for _n, l in fences] == ["python", "", "rust", ""], fences
    assert [t for _n, _l, t in heads] == ["Title", "Dup", "Dup", "Other"], heads
    # a fence opened with ``` inside a ~~~ block must not close it
    q = os.path.join(d, "b.md")
    open(q, "w", encoding="utf-8", newline="\n").write("~~~\n```\n~~~\n```js\nx\n```\n")
    f2, _h2 = scan(q)
    assert [l for _n, l in f2] == ["", "js"], f2
    e = os.path.join(d, "en.md")
    z = os.path.join(d, "zh.md")
    open(e, "w", encoding="utf-8", newline="\n").write("| a | b |\n| --- | --- |\n| 1 | 2 |\n\n```bash\nls\n```\n\n[x](A.java)\n")
    open(z, "w", encoding="utf-8", newline="\n").write("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    ce, cz = counts(e), counts(z)
    assert (ce["table"], ce["fence"], ce["srclink"]) == (1, 1, 1), ce
    assert (cz["table"], cz["fence"], cz["srclink"]) == (1, 0, 0), cz
    print(f"selftest ok  fences={[l for _n, l in fences]} heads={[t for *_x, t in heads]} "
          f"struct={ce['fence']}/{ce['table']}/{ce['srclink']}")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    mode = sys.argv[1]
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 20
    if mode == "selftest":
        selftest()
        return
    if len(sys.argv) < 3:
        print(__doc__)
        return
    root = sys.argv[2].rstrip("/\\")
    {"fence": cmd_fence, "dup": cmd_dup, "parity": cmd_parity, "struct": cmd_struct}[mode](root, cap)


if __name__ == "__main__":
    main()
