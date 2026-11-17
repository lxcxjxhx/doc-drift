#!/usr/bin/env python3
"""Precise broken-link scan for docs trees (md/rst/mdx), with an optional path filter.

Usage: python pr-work/_tools/docs_links.py <repo> [--only-prefix docs] [--max 25]

Only reports links/images whose resolved target is inside --only-prefix (so sparse
clones and links that legitimately point outside the docs tree do not create noise).
"""
import os
import sys
import urllib.parse

SKIP = {".git", ".claude", ".agents", "node_modules", "target", "build", "dist", ".venv", "__pycache__", ".next"}
EXT = (".md", ".mdx", ".rst")
TARGET_EXT = (".md", ".mdx", ".rst", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".py", ".ipynb")
# Trees whose pages are staged or generated before the site is built: a link into them is
# correct in the output and absent from the source. `i18n/<code>/pages/` is the shape a
# translation pipeline uses (English tree + overlay); `docs/api/` is mkdocstrings output.
STAGED = ("i18n",)
GENERATED_NAMES = {"api"}


def norm(p):
    return p.replace("\\", "/")


def scan(root, only=None):
    """Return every link whose target does not exist, resolved as described above."""
    hits = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if not f.endswith(EXT):
                continue
            p = os.path.join(dirpath, f)
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            in_fence = False
            for line in txt.splitlines():
                if line.lstrip().startswith(("```", "~~~")):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue  # example paths inside code blocks are not links
                for tok in _links(line):
                    if tok.startswith(("http", "mailto:", "#", "data:")) or not tok:
                        continue
                    t = tok.split("#")[0].split("?")[0]
                    if not t or not t.endswith(TARGET_EXT):
                        continue
                    t = urllib.parse.unquote(t)
                    tgt = norm(os.path.normpath(os.path.join(dirpath, t)))
                    if os.path.exists(tgt):
                        continue
                    # A leading "/" is a *web root*, not a filesystem root: Next.js,
                    # Nextra, MkDocs and Docusaurus all serve `public/` (or `static/`)
                    # at "/". FastGPT alone had 383 false hits because `/imgs/x.png`
                    # lives in `document/public/imgs/x.png`.
                    if t.startswith("/") and _web_root_hit(dirpath, t, root):
                        continue
                    if _asset_root_hit(dirpath, t, root):
                        continue
                    if only and not norm(tgt).startswith(only):
                        continue
                    # A target inside a staged or generated tree exists in the built site,
                    # not in the source checkout: skip it rather than call it broken.
                    parts = norm(tgt).split("/")
                    if any(part in STAGED for part in parts):
                        continue
                    if any(part in GENERATED_NAMES for part in parts):
                        continue
                    hits.append((norm(os.path.relpath(p, root)), t, tgt))

    seen, uniq = set(), []
    for h in hits:
        if h in seen:
            continue
        seen.add(h)
        uniq.append(h)

    return uniq


def selftest():
    """Prove the three resolved-by-convention cases: web root, fences, neighbours."""
    import tempfile

    d = tempfile.mkdtemp(prefix="links_")
    # A bare `images/x.png` that lives in the site's asset directory is resolved by the
    # build, not by the page's own folder (DefectDojo: 3502 references, 440 names, all
    # present under docs/assets/images).
    os.makedirs(os.path.join(d, "docs", "assets", "images"), exist_ok=True)
    open(os.path.join(d, "docs", "assets", "images", "a.png"), "wb").close()
    os.makedirs(os.path.join(d, "docs", "guide"), exist_ok=True)
    with open(os.path.join(d, "docs", "guide", "g.md"), "w", encoding="utf-8") as f:
        f.write("# g" + chr(10) + chr(10) + "![x](images/a.png)" + chr(10) + chr(10)
                + "![y](images/nope.png)" + chr(10))
    os.makedirs(os.path.join(d, "docs"), exist_ok=True)
    os.makedirs(os.path.join(d, "public", "imgs"), exist_ok=True)
    open(os.path.join(d, "public", "imgs", "x.png"), "wb").close()
    with open(os.path.join(d, "docs", "b.md"), "w", encoding="utf-8") as f:
        f.write("# b\n")
    with open(os.path.join(d, "docs", "a.md"), "w", encoding="utf-8") as f:
        f.write(
            "# a\n"
            "[ok](b.md)\n"
            "[bad](missing.md)\n"
            "![img](/imgs/x.png)\n"
            "```\n"
            "[code example](nope.md)\n"
            "```\n"
        )
    got = [h[1] for h in scan(d)]
    # `images/a.png` is found under docs/assets/images and must stay quiet; `images/nope.png`
    # is the negative case that keeps the rule from suppressing every bare image path.
    assert got == ["missing.md", "images/nope.png"], got
    print("selftest ok:", got)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    root = sys.argv[1].rstrip("/\\")
    only = None
    if "--only-prefix" in sys.argv:
        only = sys.argv[sys.argv.index("--only-prefix") + 1].strip("/")
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 25
    uniq = scan(root, only)
    print(f"== {root}  broken doc links: {len(uniq)}")
    for src, target, resolved in uniq[:cap]:
        print(f"   {src}\n      -> {target}   (resolved: {resolved})")


WEB_ROOTS = ("public", "static", "assets", "docs", "")


ASSET_DIRS = ("assets/images", "static/images", "public/images", "assets/img", "images")


def _asset_root_hit(dirpath, target, root):
    """True when a bare `images/x.png` lives in the site's asset directory instead.

    DefectDojo has 3502 references shaped `images/<name>` in `docs/content/**` and all 440
    distinct names sit at `docs/assets/images/<name>`. A pipeline that moves the asset
    directory under the page tree is a convention, not 3502 typos; the link is resolved by
    the site build, so the repo-relative miss is not a defect.
    """
    if not target.startswith(("images/", "img/")):
        return False
    rel = target.split("/", 1)[1]
    node = os.path.abspath(dirpath)
    root_abs = os.path.abspath(root)
    while True:
        for sub in ASSET_DIRS:
            if os.path.exists(os.path.join(node, sub, rel)):
                return True
        if os.path.normcase(node) == os.path.normcase(root_abs):
            break
        parent = os.path.dirname(node)
        if parent == node:
            break
        node = parent
    return any(os.path.exists(os.path.join(root_abs, sub, rel)) for sub in ASSET_DIRS)


def _web_root_hit(dirpath, target, root):
    """True when a leading-"/" link resolves under a static web root.

    Tries every ancestor of the source file (nearest first) with each candidate
    root directory, then the repository root itself, which is how GitHub treats
    root-relative paths in some renderers.
    """
    rel = target.lstrip("/")
    node = os.path.abspath(dirpath)
    root_abs = os.path.abspath(root)
    while True:
        for sub in WEB_ROOTS:
            cand = os.path.join(node, sub, rel) if sub else os.path.join(node, rel)
            if os.path.exists(cand):
                return True
        if os.path.normcase(node) == os.path.normcase(root_abs):
            break
        parent = os.path.dirname(node)
        if parent == node:
            break
        node = parent
    return os.path.exists(os.path.join(root_abs, rel))


def _links(line):
    """Yield markdown link targets from one line, ignoring inline code spans.

    A link written inside backticks (``[a](a)``) is quoted text, not a link; the
    FastGPT entry in EVIDENCE/TARGETS produced two false positives that way.
    """
    import re
    out = []
    line = re.sub(r"`[^`]*`", "", line)
    for m in re.finditer(r"\]\(([^)\s]+)", line):
        out.append(m.group(1))
    for m in re.finditer(r'src="([^"]+)"', line):
        out.append(m.group(1))
    return out


if __name__ == "__main__":
    main()
