#!/usr/bin/env python3
"""Run every checker in this directory against one tree and print one table.

Each tool below keeps its own CLI; this only knows how to call them, and it says so
when a tool needs repository-specific arguments rather than guessing them.

Usage:
    python tools/run_all.py <repo>            # the portable checkers
    python tools/run_all.py <repo> --all      # include the ones that need extra arguments
    python tools/run_all.py --selftest
"""
import concurrent.futures
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# label, argv after the tool path, needs_args
SPEC = [
    ("docstrings", ["docstring_check.py", "{root}", "--max", "5"], False),
    ("docstring triage", ["docstring_triage.py", "{root}"], False),
    ("doctags", ["doctag_check.py", "{root}", "--max", "5"], False),
    ("anchors", ["anchor_check.py", "{root}", "--max", "5"], False),
    ("doc links", ["docs_links.py", "{root}", "--max", "5"], False),
    ("doc/code refs", ["docs_code_refs.py", "{root}"], False),
    ("doc/code tokens", ["docs_code_tokens.py", "{root}"], False),
    ("bilingual parity", ["docs_parity.py", "{root}"], False),
    ("md tables", ["md_table_check.py", "{root}"], False),
    ("doc commands", ["docs_task_refs.py", "{root}"], False),
    ("md fences", ["md_lint.py", "fence", "{root}"], False),  # vs the repo's own tagging convention
    ("md duplicates", ["md_lint.py", "dup", "{root}"], False),
    ("md bilingual structure", ["md_lint.py", "struct", "{root}"], False),
    ("md bilingual headings", ["md_lint.py", "parity", "{root}"], False),
    ("placeholders (ts/js)", ["locale_placeholders.py", "{root}", "--base", "en", "--others", "zh"], True),
    ("placeholders (json ns)", ["i18n_placeholders.py", "{root}"], True),
]


def run(root, argv, timeout=600):
    tool = os.path.join(HERE, argv[0])
    if not os.path.exists(tool):
        return {"label": None, "error": f"{argv[0]} missing"}
    started = time.monotonic()
    try:
        p = subprocess.run([PY, tool] + [a.replace("{root}", root) for a in argv[1:]],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"label": None, "secs": timeout, "error": "timeout"}
    out = p.stdout.strip().splitlines()
    summary = next((l for l in out if l.strip()), "")
    findings = sum(1 for l in out if l.startswith(("  ", "\t")) and l.strip())
    return {"label": None, "secs": round(time.monotonic() - started, 1),
            "rc": p.returncode, "summary": summary, "findings": findings,
            "error": (p.stderr.strip().splitlines()[-1]
                      if "Traceback" in p.stderr or p.returncode not in (0, 1) else None)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--selftest" in sys.argv:
        root = os.path.join(os.path.dirname(HERE), "fixtures")
        rows = [run(root, argv) | {"label": label} for label, argv, needs in SPEC if not needs]
        # a checker may exit 1 to mean "found something"; only a traceback is a real failure
        assert all(r.get("error") is None for r in rows), [r for r in rows if r.get("error")]
        assert len(rows) >= 10, len(rows)
        doc = next(r for r in rows if r["label"] == "docstrings")
        assert "stale-args=1" in doc["summary"], doc["summary"]
        print(f"selftest ok  ran={len(rows)}  docstring summary={doc['summary']!r}")
        return 0
    if not args:
        print(__doc__)
        return 2
    root = os.path.abspath(args[0])
    if not os.path.isdir(root):
        print(f"not a directory: {root}")
        return 2
    include_all = "--all" in sys.argv
    todo = [(l, a) for l, a, needs in SPEC if include_all or not needs]
    skipped = [l for l, a, needs in SPEC if needs and not include_all]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(run, root, argv): label for label, argv in todo}
        rows = []
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            r["label"] = futs[f]
            rows.append(r)
    order = {label: i for i, (label, _) in enumerate(todo)}
    rows.sort(key=lambda r: order[r["label"]])

    print(f"# doc-drift · {root}\n")
    print("| checker | findings | time | summary |")
    print("|---|---:|---:|---|")
    for r in rows:
        summary = (r.get("summary") or r.get("error") or "").replace("|", "\\|")[:110]
        print(f"| {r['label']} | {r.get('findings', '?')} | {r.get('secs', '?')}s | {summary} |")
    if skipped:
        print(f"\nnot run (needs repository-specific arguments, use --all): {', '.join(skipped)}")
    bad = [r for r in rows if r.get("error")]
    if bad:
        print("\nfailed:")
        for r in bad:
            print(f"  {r['label']}: {r.get('error')}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
