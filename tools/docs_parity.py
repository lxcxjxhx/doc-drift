#!/usr/bin/env python3
"""Find bilingual docs drift: pages that exist in one language tree but not the other.

Usage: python pr-work/_tools/docs_parity.py <repo> [--en en] [--zh zh]

Works for repos that mirror docs under two locale dirs (en/zh, en/zh-CN, docs/en + docs/zh, ...).
Prints missing counterparts, newest-first, plus the zh/en ratio.
"""
import os
import sys

SKIP = {".git", "node_modules", "images", "assets", "img", "static", "public", ".vitepress", ".vuepress"}
PAIRS = [("en", "zh"), ("en", "zh-CN"), ("en-US", "zh-CN"), ("en", "zh_CN")]


def find_locale_root(repo):
    """Return (base, en_dirname, zh_dirname) for the first locale pair that exists."""
    cands = []
    for root, dirs, _ in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP]
        if root.count(os.sep) - repo.count(os.sep) > 3:
            dirs[:] = []
            continue
        for en, zh in PAIRS:
            if en in dirs and zh in dirs:
                cands.append((root, en, zh))
    if not cands:
        return None
    # prefer the shallowest / most populated pair
    cands.sort(key=lambda c: (c[0].count(os.sep), ))

    def size(c):
        return sum(len(f) for _, _, f in os.walk(os.path.join(c[0], c[1])))

    cands.sort(key=lambda c: -size(c))
    return cands[0]


def rels(base, lang):
    out = set()
    root = os.path.join(base, lang)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in files:
            if f.endswith((".md", ".mdx")):
                out.add(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    repo = sys.argv[1].rstrip("/\\")
    pair = find_locale_root(repo)
    if not pair:
        print("no locale pair found")
        return
    base, en, zh = pair
    E, Z = rels(base, en), rels(base, zh)
    print(f"base={os.path.relpath(base, repo)}  {en}={len(E)}  {zh}={len(Z)}")
    only_zh = sorted(Z - E)
    only_en = sorted(E - Z)
    print(f"\n缺失 {en} 版本（{en} 缺 {len(only_zh)} 页）:")
    for p in only_zh[:40]:
        print("  ", p)
    print(f"\n缺失 {zh} 版本（{zh} 缺 {len(only_en)} 页）:")
    for p in only_en[:25]:
        print("  ", p)


if __name__ == "__main__":
    main()
