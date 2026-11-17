#!/usr/bin/env python3
"""Classify docstring-parameter findings as real drift or kwargs-ambiguous.

`docstring_check.py` already skips names the body reads back out of `**kwargs`,
so what reaches this tool is either real drift or a function that forwards
`**kwargs` to something else. That distinction decides whether a finding is worth
a PR, and it must not be guessed.

For every finding it prints: the documented names that are missing from the
signature, whether the function takes `**kwargs`, which of those names are read
from it, and whether it forwards `**kwargs` onward.

usage: python pr-work/_tools/docstring_triage.py <repo> [--limit 40]
exit 1 when at least one finding is "real drift" (so it can gate a batch).
"""
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docstring_check as checker  # noqa: E402


def analyse(path, lineno, fn_name):
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            if node.lineno <= lineno <= (node.end_lineno or node.lineno):
                target = node
                break
    if target is None:
        return None
    has_kwargs = target.args.kwarg is not None
    body = ast.get_source_segment(src, target) or ""
    reads = set(re.findall(r"kwargs(?:\.get\(|\[)\s*[\"'](\w+)[\"']", body))
    forwards = re.findall(r"[\w\.]+\(\s*\*\*kwargs\s*\)", body) or re.findall(
        r"\*\*kwargs\s*[,)]", body
    )
    return {"has_kwargs": has_kwargs, "reads": reads, "forwards": bool(forwards)}


def scan_repo(root, limit=40, verbose=True):
    """Return (tally, rows) for one repository; usable from other tools."""
    tally = {"real": 0, "consumed": 0, "ambiguous": 0, "unresolved": 0}
    rows = []
    printed = 0
    for p in checker.walk(root):
        for path, line, fn_name, kind, names in checker.check_file(p):
            if kind != "args":
                continue
            info = analyse(path, line, fn_name)
            rel = path.replace(chr(92), "/")
            if info is None:
                tally["unresolved"] += 1
                verdict = "unresolved"
            elif info["reads"] & set(names):
                tally["consumed"] += 1
                verdict = f"consumed: {sorted(info['reads'] & set(names))}"
            elif info["has_kwargs"] and info["forwards"]:
                tally["ambiguous"] += 1
                verdict = "ambiguous: **kwargs forwarded"
            else:
                tally["real"] += 1
                verdict = "REAL drift"
            rows.append((rel, line, fn_name, names, verdict))
            if verbose and verdict.startswith(("REAL", "ambig")) and printed < limit:
                print(f"{rel}:{line}  {fn_name}()  missing={names}  -> {verdict}")
                printed += 1
    return tally, rows


def selftest():
    """Three functions the docstring checker flags: one reads the name out of **kwargs
    (consumed, not a defect), one forwards **kwargs (ambiguous), one does neither
    (real drift). Getting the first two wrong is what makes this tool noisy."""
    import tempfile

    d = tempfile.mkdtemp(prefix="triage_")
    path = Path(d) / "m.py"
    path.write_text(
        'def consumed(a, **kwargs):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '        process (obj): read back out.\n'
        '    """\n'
        '    return kwargs.get("process")\n'
        '\n'
        'def forwarded(a, **kwargs):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '        process (obj): passed along.\n'
        '    """\n'
        '    return helper(**kwargs)\n'
        '\n'
        'def real(a):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '        gone (int): removed.\n'
        '    """\n'
        '    return a\n',
        encoding="utf-8")
    tally, rows = scan_repo(d, verbose=False)
    verdicts = {r[2]: r[4] for r in rows}
    # `docstring_check` drops two shapes before this layer sees them: names the body reads
    # back out of **kwargs, and bodies that hand **kwargs on to another call
    # (`helper(**kwargs)`). So neither the "consumed" nor the "ambiguous" branch is
    # reachable from here — that is the layering working, and the fixture asserts it
    # instead of pretending those branches were exercised.
    assert "consumed" not in verdicts, verdicts
    assert "forwarded" not in verdicts, verdicts
    assert tally["ambiguous"] == 0, tally
    assert tally["real"] == 1, tally
    assert verdicts["real"] == "REAL drift", verdicts
    print(f"selftest ok  real={tally['real']} ambiguous={tally['ambiguous']} "
          f"(kwargs-read and kwargs-forwarded cases both filtered upstream)")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return 0
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    root = sys.argv[1].rstrip("/\\")
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 40
    tally, _ = scan_repo(root, limit=limit)
    print()
    print(f"{root}: real={tally['real']} consumed={tally['consumed']} "
          f"ambiguous={tally['ambiguous']} unresolved={tally['unresolved']}")
    return 0 if tally["real"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
