#!/usr/bin/env python3
"""Check that Python snippets in docs import symbols the package still exposes.

Renames and removals break documentation examples silently: the prose keeps
working, the snippet fails for the reader. This walks fenced ```python blocks in
Markdown, resolves every `from pkg.mod import name` against the source tree by
AST, and reports names that the module no longer defines.

Deliberately conservative: a module that uses a star import or a module-level
`__getattr__` makes its names "unknown", not missing; a name re-exported through
`__all__` or a plain assignment counts as present.

usage: python pr-work/_tools/docs_code_refs.py <repo> [--max 20]
"""
import ast
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".agents", ".claude", "node_modules", ".venv", "build", "dist", "__pycache__", "third_party", "third-party"}
FENCE = re.compile(r"```(?:python|py)[ \t]*\n(.*?)```", re.S)
# Pages that exist to name symbols which no longer exist are not defects.
MIGRATION = re.compile(r"(?i)^(migration|migrating|upgrad\w*|changelog|changes|release-notes)\b")


def source_modules(root: Path):
    """Map dotted relative paths (as a package root) to files."""
    mods = {}
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = p.relative_to(root).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods[".".join(parts)] = p
    return mods


class ModuleIndex:
    def __init__(self, root: Path):
        self.root = root
        self.mods = source_modules(root)
        self._cache = {}

    def find(self, dotted: str):
        if dotted in self.mods:
            return self.mods[dotted]
        for prefix in ("src", "python"):
            key = f"{prefix}.{dotted}"
            if key in self.mods:
                return self.mods[key]
        # longest-suffix match, e.g. "llmcompressor.foo" -> ".../llmcompressor/foo.py"
        for key, path in self.mods.items():
            if key.endswith("." + dotted) or key == dotted:
                return path
        return None

    def names(self, path: Path):
        if path in self._cache:
            return self._cache[path]
        defined, unknown = set(), False
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            self._cache[path] = None
            return None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined.add(node.target.id)
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    unknown = True
                for a in node.names:
                    defined.add(a.asname or a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    defined.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, (ast.If, ast.Try)):
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        defined.add(sub.name)
                    elif isinstance(sub, ast.ImportFrom):
                        for a in sub.names:
                            defined.add(a.asname or a.name)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
        # __all__ entries count as exported
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            defined.add(elt.value)
        self._cache[path] = (defined, unknown)
        return self._cache[path]


def local_packages(root: Path):
    """Top-level names that belong to this repository (so third-party imports are skipped)."""
    names = set()
    for base in (root, root / "src", root / "python"):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "__init__.py").exists():
                names.add(child.name)
            elif child.suffix == ".py" and child.stem != "__init__":
                names.add(child.stem)
    return names


def scan(root):
    """Return (doc, line, module, name) for own-package imports the package cannot satisfy."""
    root = Path(root)
    index = ModuleIndex(root)
    local = local_packages(root)

    hits = []
    for doc in root.rglob("*"):
        if doc.suffix not in (".md", ".mdx", ".rst") or any(p in SKIP_DIRS for p in doc.parts):
            continue
        # A migration guide names the *old* module paths on purpose; that is its job.
        # Changelogs do the same for the release that moved them.
        if MIGRATION.match(doc.name):
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for m in FENCE.finditer(text):
            block = m.group(1)
            line_no = text[: m.start()].count("\n") + 2
            try:
                tree = ast.parse(block)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or not node.module or node.level:
                    continue
                if node.module.split(".")[0] not in local:
                    continue
                path = index.find(node.module)
                if path is None:
                    hits.append((doc, line_no + (node.lineno or 0) - 1, node.module, "<module>"))
                    continue
                got = index.names(path)
                if got is None:
                    continue
                defined, unknown = got
                if unknown:
                    continue
                for alias in node.names:
                    if alias.name == "*" or alias.name in defined:
                        continue
                    if index.find(f"{node.module}.{alias.name}") is not None:
                        continue
                    hits.append((doc, line_no + (node.lineno or 0) - 1, node.module, alias.name))
    return hits


def selftest():
    """An own-package symbol the module no longer defines is reported; a real one, a
    submodule import, and a third-party import are not."""
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="dcr_"))
    pkg = d / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (pkg / "sub.py").write_text("VALUE = 1\n", encoding="utf-8")
    (d / "guide.md").write_text(
        "```python\n"
        "from pkg import ok\n"
        "from pkg import sub\n"
        "import requests\n"
        "```\n\n"
        "```python\n"
        "from pkg import gone\n"
        "```\n",
        encoding="utf-8",
    )
    hits = [(doc.name, mod, name) for doc, _ln, mod, name in scan(d)]
    assert hits == [("guide.md", "pkg", "gone")], hits
    print(f"selftest ok  hits={hits}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    root = Path(sys.argv[1])
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 20
    hits = scan(root)

    print(f"== {root}  doc-import mismatches: {len(hits)}")
    for doc, line, mod, name in hits[:cap]:
        print(f"   {doc.relative_to(root)}:{line}  from {mod} import {name}")


if __name__ == "__main__":
    main()
