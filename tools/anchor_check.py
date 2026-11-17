#!/usr/bin/env python3
"""Find markdown links whose #fragment does not match any heading anchor.

Usage: python pr-work/_tools/anchor_check.py <docs_root> [--max 30]

Slug rules follow GitHub's heading anchor algorithm closely enough for a
high-precision report: lowercase, drop punctuation, spaces -> '-'.
"""
import os
import re
import sys
import urllib.parse

SKIP_DIRS = {".git", "node_modules", ".next", "public"}
STYLE = os.environ.get("ANCHOR_STYLE", "github")
# docs.json / docs/docs.json is Mintlify's marker; when present the docs tree is
# slugged by the site, not by GitHub. Auto-detect so a plain run is correct.
MINTLIFY = False
MKDOCS = False
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def slug(text, style="github"):
    # A heading can be a link ("### [Offline Batch Inference](./x.py)"); the anchor
    # comes from the link text, not from the URL. Without this, sglang's
    # examples/runtime/engine/readme.md produced 5 bogus misses.
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1), text)
    t = text.strip().lower()
    if style == "mintlify":
        # Mintlify (docs.sglang.io, most 2026 vendor docs) turns "." into "-",
        # so "### 3.8 Unified Cache ..." renders as id="3-8-unified-cache-...".
        # Verified by fetching the rendered page and reading the id attribute;
        # with GitHub rules the same heading is "38-...", which made 138 correct
        # links look broken in sglang's cookbook.
        # Only a dot *between* word characters becomes a hyphen ("3.8" -> "3-8");
        # a sentence number keeps none ("3. Benchmark" -> "3-benchmark-results").
        # Both verified by reading the id attribute of the rendered page.
        t = re.sub(r"(?<=[0-9a-z])\.(?=[0-9a-z])", "-", t)
    t = re.sub(r"`|\*|~", "", t)  # GitHub keeps underscores in anchors
    # GitHub keeps emoji variation selectors (U+FE0F/U+FE0E) in the anchor:
    # "## <wrench> Developing Pipecat" renders as "#<VS16>-developing-pipecat".
    # Verified against the rendered README DOM, not the algorithm description.
    t = re.sub(r"[^\w\u4e00-\u9fff\ufe0f\ufe0e\- ]", "", t)
    # Do NOT strip before converting spaces: a heading like "`# contract-check: skip-install`"
    # keeps the leading dash GitHub generates (verified against the rendered README).
    t = t.rstrip().replace(" ", "-")
    if style == "python-markdown":
        # mkdocs (python-markdown) *collapses* runs of hyphens and spaces, so
        # "## Docker / production" is `docker-production` there and `docker--production`
        # on GitHub. Applying GitHub rules to a docs/ tree under mkdocs.yml made 18 of
        # agenticos' correct cross-file anchors look dead.
        t = re.sub(r"[-\s]+", "-", t)
    # NOTE: GitHub does not collapse consecutive hyphens: "State & Persistence"
    # becomes "state--persistence", so no extra collapsing here.
    return t


def headings(path):
    out = set()
    seen = {}
    IDATTR = re.compile(r'(?:id|name)="?([^"\s>]+)"?')
    MYST = re.compile(r"^\(([\w.:-]+)\)=\s*$")  # Sphinx/MyST explicit target
    # mkdocs / python-markdown attr_list: "## 見出し {#english-id}" renders the
    # anchor as the given id, NOT as the slug of the translated heading.
    # Without this, the Japanese OpenAI Agents docs produced 25 false positives.
    # Some repositories write the id with spaces inside the braces: `## Settings { #settings }`.
    # Accepting only `{#id}` made 1677 cross-file anchors in one mkdocs repository look dead.
    ATTR = re.compile(r"\{\s*#([^}\s]+)\s*\}")
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            for m2 in IDATTR.finditer(line):
                out.add(m2.group(1))
            m3 = MYST.match(line.strip())
            if m3:
                out.add(m3.group(1))
            m = HEADING.match(line)
            if not m:
                continue
            attrs = ATTR.findall(m.group(1))
            if attrs:
                out.update(attrs)
                continue
            # Files under docs/ are rendered by the docs site (Mintlify);
            # everything else is rendered by GitHub, whatever ANCHOR_STYLE says.
            posix = path.replace(os.sep, "/")
            under_docs = posix.startswith("docs/") or "/docs/" in posix
            if MINTLIFY and under_docs:
                style = "mintlify"
            elif MKDOCS and under_docs:
                style = "python-markdown"
            else:
                style = "github"
            s = slug(m.group(1), style)
            if s in seen:
                seen[s] += 1
                out.add(f"{s}-{seen[s]}")
            else:
                seen[s] = 0
                out.add(s)
    except OSError:
        return set()
    return out


def selftest():
    import tempfile

    d = tempfile.mkdtemp(prefix="anchor_")
    idx = os.path.join(d, "a.md")
    open(idx, "w", encoding="utf-8").write(
        "# Title\n"
        "## ツール使用の動作 {#tool-use-behavior}\n"
        "## Plain heading\n"
        "[ok](#tool-use-behavior) [ok](#plain-heading)\n"
        "[bad](#nope)\n"
    )
    got = sorted(headings(idx))
    assert got == ["plain-heading", "title", "tool-use-behavior"], got
    # Mintlify rule: "### 3.8 Foo" -> "3-8-foo" (dots become hyphens).
    assert slug("3.8 Unified Cache (UMBP)", "mintlify") == "3-8-unified-cache-umbp"
    assert slug("3. Benchmark results", "mintlify") == "3-benchmark-results"
    assert slug("Docker / production", "python-markdown") == "docker-production"
    assert slug("Docker / production", "github") == "docker--production"
    assert slug("3.8 Unified Cache (UMBP)", "github") == "38-unified-cache-umbp"
    print("selftest ok:", got)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    root = sys.argv[1].rstrip("/\\")
    global MINTLIFY, MKDOCS
    MINTLIFY = os.path.exists(os.path.join(root, "docs.json")) or os.path.exists(
        os.path.join(root, "docs", "docs.json"))
    MKDOCS = os.path.exists(os.path.join(root, "mkdocs.yml")) or         os.path.exists(os.path.join(root, "mkdocs.yaml"))
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 30

    cache, bad = {}, []
    files = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in fs:
            if f.endswith((".md", ".mdx")):
                files.append(os.path.join(dp, f))

    for p in files:
        if p not in cache:
            cache[p] = headings(p)
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in LINK.finditer(txt):
            target = m.group(1)
            if target.startswith(("http", "mailto:", "data:")) or "#" not in target:
                continue
            path, _, frag = target.partition("#")
            if not frag:
                continue
            frag = urllib.parse.unquote(frag)
            if path:
                tp = os.path.normpath(os.path.join(os.path.dirname(p), urllib.parse.unquote(path)))
                if not tp.endswith((".md", ".mdx")):
                    tp += ".mdx" if os.path.exists(tp + ".mdx") else ".md"
                if not os.path.exists(tp):
                    continue  # broken file links are reported by docs_links.py
            else:
                tp = p
            if tp not in cache:
                cache[tp] = headings(tp)
            if cache[tp] and frag not in cache[tp] and frag.lower() not in cache[tp]:
                bad.append((os.path.relpath(p, root), target))

    print(f"files={len(files)}  bad-anchors={len(bad)}")
    for src, tgt in bad[:cap]:
        print(f"   {src}  ->  {tgt}")


if __name__ == "__main__":
    main()
