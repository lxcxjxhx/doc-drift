#!/usr/bin/env python3
"""Report docstring parameter sections that document parameters the function
does not accept (stale after a signature change), and functions that document
a return value they cannot produce.

Proven class: pipecat #6522 was merged for exactly this — two methods whose
Args block survived the removal of their last parameter.

Usage:
  python pr-work/_tools/docstring_check.py <repo_or_dir> [--max 40] [--returns]
  python pr-work/_tools/docstring_check.py selftest

Only the "documented but not in the signature" direction is reported by
default: it is almost never intentional, while an undocumented parameter is
merely incomplete and very common.
"""
import ast
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "build", "dist", "__pycache__", ".tox"}
SECTION = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:?\s*$")
NUMPY_HEAD = re.compile(r"^\s*(Parameters|Other Parameters)\s*$")
ENTRY = re.compile(r"^(\s*)(\*{0,2}[A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:")
RETURNS = re.compile(r"^\s*Returns?\s*:?\s*$")
SECTION_WORDS = {"returns", "return", "outputs", "output", "raises", "yields",
                 "examples", "example",
                 "notes", "note", "references", "attributes", "warnings", "todo",
                 "see also", "usage"}
NUMPY_STOP = {"Returns", "Yields", "Raises", "Notes", "Examples", "References",
                    "See Also", "Attributes", "Warnings", "Todo", "Outputs", "Output"}
# vLLM writes `Outputs:` for out-params it returns; without this the section's
# entries parse as parameters (13 hits, 3 of them core `_custom_ops.py`).
# SGLang writes `Shape:` blocks (`- input: (n, m)`); without it `Shape` itself
# became the "parameter" for three cutlass_w4a8_moe kernels.
STOP = re.compile(
    r"^\s*(Returns?|Outputs?|Raises|Yields|Examples?|Notes?|Note|See Also|Attributes"
    r"|References|Warnings?|Todo|Usage|Example usage|Shapes?)\s*::?\s*$"
)


def documented_params(doc):
    """Names listed in the parameter section of a Google- or numpydoc-style docstring.

    Handles both layouts because the repos mix them: `Args:` / `Arguments:` /
    `Parameters:` followed by indented entries, and the numpydoc `Parameters`
    + underline + `name : type` form.
    """
    lines = doc.split("\n")
    start, numpy = None, False
    for i, line in enumerate(lines):
        if re.match(r"^\s*(Args|Arguments|Parameters)\s*:?\s*$", line):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            numpy = j < len(lines) and bool(re.match(r"^\s*-{3,}\s*$", lines[j]))
            start = j + 1 if numpy else i + 1
            break
    if start is None:
        return []

    names, indent = [], None
    for line in lines[start:]:
        if not line.strip():
            continue
        if indent is None and re.match(r"^\s*-\s+\*{0,2}[A-Za-z_]\w*", line):
            # list-style `- name (type): desc` args are not parsed — say so, never guess.
            # Guessing produced a phantom `Shape` param on three cutlass_w4a8_moe kernels.
            return []
        if numpy and line.strip() in NUMPY_STOP:
            break          # next numpydoc section starts (Returns, Raises, ...)
        if not numpy and STOP.match(line):
            break
        m = ENTRY.match(line) or (re.match(r"^(\s*)(\*{0,2}[A-Za-z_]\w*)\s*$", line) if numpy else None)
        if m:
            if indent is None:
                indent = len(m.group(1))
            if m.group(2).lower() in SECTION_WORDS:
                break          # `Returns: A tensor ...` is a section, not an entry
            if len(m.group(1)) == indent:
                if numpy and m.group(2).lower() in ("none", "none."):
                    return []  # numpydoc writes "None" under Parameters when there are none
                names.append(m.group(2))
            continue
        if numpy:
            if indent is not None and len(line) - len(line.lstrip()) > indent:
                continue       # description line of the entry above
            continue
        if indent is not None and len(line) - len(line.lstrip()) < indent:
            break
    return names


def has_returns(doc):
    """True when the docstring documents a return value other than None.

    `Returns: None` on a function that returns nothing is accurate, so it is not
    drift; the Inworld/AIC services use that style throughout.
    """
    lines = doc.split("\n")
    for i, line in enumerate(lines):
        if not RETURNS.match(line):
            continue
        for follow in lines[i + 1:]:
            if not follow.strip():
                continue
            if re.match(r"^\s*-{3,}\s*$", follow):
                continue  # numpydoc underline: the value follows it
            first = follow.strip().lower()
            return not (first.startswith("none") or first.startswith("nothing")
                        or first.startswith("no return"))
        return False
    return False


def is_abstract(node):
    """An interface method: the body only raises NotImplementedError or is a stub.

    Its docstring is the contract, so "Returns:" on such a method is correct even
    though no return statement exists. Skipping them is what keeps this check
    from reporting every ABC in a codebase (50 such hits in pipecat alone).
    """
    for stmt in node.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring or `...`
        if isinstance(stmt, ast.Raise):
            continue
        return False
    return True


def kwargs_forwarded(node):
    """Keyword names the body reads back out of its own `**kwargs`.

    A constructor declared as `def __init__(self, **kwargs)` still accepts
    `process=`/`token=` and documents them, reading them with kwargs.get(...).
    Reporting those would be a false positive (rocketride DbgStdio); only names
    the body never extracts are drift.
    """
    if node.args.kwarg is None:
        return set()
    kw = node.args.kwarg.arg
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr in ("get", "pop", "setdefault") \
                and isinstance(sub.func.value, ast.Name) and sub.func.value.id == kw and sub.args \
                and isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str):
            names.add(sub.args[0].value)
        elif isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Name) \
                and sub.value.id == kw and isinstance(sub.slice, ast.Constant) \
                and isinstance(sub.slice.value, str):
            names.add(sub.slice.value)
    return names


def kwargs_blind(node):
    """True when `**kwargs` is handed to another call, whole or unpacked.

    Two shapes count, both of which accept every documented option and hand it on:
    `super().__init__(*args, **kwargs)` (unpacked) and
    `self.options = self.parse_options(kwargs)` (the dict passed along, which is how
    harbor's environment classes resolve 20 documented sandbox options). Neither is
    drift. A body that only pulls one key out of `**kwargs` and ignores the rest is
    a different case, and the selftest pins that negative one.
    """
    a = node.args
    if a.kwarg is None:
        return False
    name = a.kwarg.arg
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        if any(isinstance(x, ast.Name) and x.id == name for x in sub.args):
            return True
        for kw in sub.keywords:
            if kw.arg is None and isinstance(kw.value, ast.Name) and kw.value.id == name:
                return True
    return False


def has_overload(tree, name):
    """True when the module declares this name with `@overload` at least once."""
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or n.name != name:
            continue
        for d in n.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            if getattr(target, "id", None) == "overload" or \
                    getattr(target, "attr", None) == "overload":
                return True
    return False


def check_file(path):
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        a = node.args
        params = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
        params |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
        params -= {"self", "cls"}
        # The implementation `def f(*args, **kwargs)` above a set of `@overload`s takes its
        # real signature from the overloads, so the docstring documents parameters the body
        # never names. agno's `insert_many` and `tool` are exactly this shape.
        positional = [x.arg for x in a.posonlyargs + a.args if x.arg not in ("self", "cls")]
        if (a.vararg is not None and a.kwarg is not None and not positional
                and not a.kwonlyargs and has_overload(tree, node.name)):
            continue
        kwargs_names = kwargs_forwarded(node)
        # A function that hands its `**kwargs` on to another call accepts every documented
        # name (`super().__init__(*args, **kwargs)`, `self.parse_options(kwargs)`); any
        # "documented but not in the signature" finding there is noise.
        if not kwargs_blind(node):
            # `self` / `cls` are receivers: documenting them is a style choice, not drift.
            stale = [n for n in documented_params(doc)
                     if n.lstrip("*") not in params and n.lstrip("*") not in ("self", "cls")
                     and n.lstrip("*") not in kwargs_names]
            if stale:
                out.append((path, node.lineno, node.name, "args", stale))
        # a function that documents Returns but never returns a value
        if (has_returns(doc) and not is_abstract(node)
                and not any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(node))
                and not any(isinstance(n, ast.Return) and n.value is not None
                            for n in ast.walk(node))):
            out.append((path, node.lineno, node.name, "returns", []))
    return out


def walk(root):
    if os.path.isfile(root):
        yield root
        return
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fs:
            if f.endswith(".py"):
                yield os.path.join(dp, f)


def _fixture(name):
    """Locate a fixture whether the tools sit beside `fixtures/` or beside `_data/fixtures/`."""
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in (("..", "fixtures", name), ("..", "_data", "fixtures", name)):
        p = os.path.join(here, *rel)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(name)


def selftest():
    import tempfile

    d = tempfile.mkdtemp(prefix="docstring_")
    p = os.path.join(d, "s.py")
    open(p, "w", encoding="utf-8", newline="\n").write(
        'def ok(a, b):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '        b (str): second.\n'
        '    """\n'
        '    return a\n'
        '\n'
        'def stale(a):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '        gone (int): removed parameter.\n'
        '    """\n'
        '\n'
        'def stars(a, **kw):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '        **kw: rest.\n'
        '    """\n'
        '\n'
        'def numpy_style(a):\n'
        '    """Do it.\n'
        '\n'
        '    Parameters\n'
        '    ----------\n'
        '    a : int\n'
        '        first.\n'
        '    old : int\n'
        '        removed.\n'
        '    """\n'
        '\n'
        'def no_return(a):\n'
        '    """Do it.\n'
        '\n'
        '    Returns:\n'
        '        int: never.\n'
        '    """\n'
        '    print(a)\n'
        '\n'
        'def abstract_with_returns(a):\n'
        '    """Do it.\n'
        '\n'
        '    Returns:\n'
        '        int: the contract.\n'
        '    """\n'
        '    raise NotImplementedError\n'
        '\n'
        'def example_trap(a):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        a (int): first.\n'
        '\n'
        '    Example::\n'
        '\n'
        '        try: run(a)\n'
        '    """\n'
        '\n'
        'def kwargs_documented(**kwargs):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        process (obj): read back out of kwargs.\n'
        '        **kwargs: rest.\n'
        '    """\n'
        '    return kwargs.get("process")\n'
        '\n'
        'def kwargs_not_read(**kwargs):\n'
        '    """Do it.\n'
        '\n'
        '    Args:\n'
        '        gone (obj): still drift, kwargs never reads it.\n'
        '        **kwargs: rest.\n'
        '    """\n'
        "    return kwargs.get('other')\n"
        '\n'
        'def outputs_section(input_tensor, topk):\n'
        '    """Quantize it.\n'
        '\n'
        '    Args:\n'
        '        input_tensor: the input.\n'
        '        topk: routed experts.\n'
        '    Outputs:\n'
        '        output: quantized tensor.\n'
        '        output_scales: blockscales.\n'
        '    """\n'
        '    return input_tensor, topk\n'
    )
    found = check_file(p)
    kinds = sorted((f[2], f[3], tuple(f[4])) for f in found)
    assert kinds == [
        ("kwargs_not_read", "args", ("gone",)),
        ("no_return", "returns", ()),
        ("numpy_style", "args", ("old",)),
        ("stale", "args", ("gone",)),
    ], kinds
    fixture = _fixture("numpy_sections.py")
    np_found = [(f[2], f[3], tuple(f[4])) for f in check_file(fixture)]
    assert np_found == [("numpy_stale", "args", ("gone",))], np_found
    assert [h for h in np_found if h[0] == "numpy_sections"] == [], np_found
    assert [h for h in np_found if h[0] == "list_style_args"] == [], np_found
    none_fixture = _fixture("numpydoc_none.py")
    none_found = [(f[2], f[3], tuple(f[4])) for f in check_file(none_fixture)]
    assert none_found == [], none_found
    # An implementation that is `*args, **kwargs` above `@overload`s documents the overload
    # signature; reporting it as drift was agno's `insert_many` and `tool`.
    over_fixture = _fixture("kwargs_not_read.py")
    over_found = [(f[2], f[3], tuple(f[4])) for f in check_file(over_fixture)]
    assert over_found == [], over_found
    print(f"selftest ok  found={kinds}  numpy={np_found}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "selftest":
        selftest()
        return
    root = sys.argv[1].rstrip("/\\")
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 40
    with_returns = "--returns" in sys.argv

    args_hits, ret_hits, files = [], [], 0
    for p in walk(root):
        files += 1
        for path, line, fn, kind, names in check_file(p):
            rel = os.path.relpath(path, root)
            if kind == "args":
                args_hits.append((rel, line, fn, names))
            elif with_returns:
                ret_hits.append((rel, line, fn))
    print(f"root={os.path.basename(root) or root}  files={files}  "
          f"stale-args={len(args_hits)}  bogus-returns={len(ret_hits) if with_returns else 'n/a'}")
    for rel, line, fn, names in args_hits[:cap]:
        print(f"   {rel}:{line}  {fn}()  documents {names}")
    for rel, line, fn in ret_hits[:cap]:
        print(f"   {rel}:{line}  {fn}()  documents Returns but never returns")


if __name__ == "__main__":
    main()
