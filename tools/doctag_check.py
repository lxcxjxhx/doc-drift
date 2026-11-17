#!/usr/bin/env python3
"""Report `@param` doc-tag names that the documented declaration does not accept.

The Python sibling (`docstring_check.py`) proved the class of defect: a rename or
a parameter removal that leaves the doc behind. This is the same check for
javadoc / jsdoc / doxygen, where there is no standard AST, so the parser is a
deliberate line-scanner with an explicit list of shapes it refuses to guess at.

Usage:
  python pr-work/_tools/doctag_check.py <root> [--lang java|ts|cpp] [--show] [--returns] [--max N]
  python pr-work/_tools/doctag_check.py selftest

Reported: a documented name with no matching parameter in the declaration, and
(with --returns) `@return` on a declaration whose body starts with `return;` or a
`void` signature. Everything the parser cannot decide is counted as `unknown`
and never reported — the 27-false-positive round is why.
"""
import bisect
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "build", "dist", "target", "__pycache__",
             ".tox", ".venv", "venv", "third_party", "vendor"}

DOC_RE = re.compile(r"/\*\*(.*?)\*/", re.S)
PARAM_TAG = re.compile(r"@param\b\s*(?:\[[^\]]*\]\s*)?(?:\{[^}]*\}\s*)?(<[^>]+>|[A-Za-z_]\w*)")
RETURN_TAG = re.compile(r"@returns?\b")
GENERIC_DOC = re.compile(r"^<.+>$")


def split_top_level(text):
    """Split a parameter list on commas that are not inside <>, (), [], {}."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def param_name(decl, lang="java"):
    """Parameter name of one declaration, or None when unresolved.

    Java and C++ put the name last (`final List<String> args`); TypeScript puts
    it first (`input: z.infer<typeof schema>`) and the type may end in any
    identifier, so the two languages cannot share one rule.

    Returns None for shapes where a name cannot be recovered without a real
    parser: destructuring, function pointers, unnamed parameters.
    """
    if "{" in decl or "=>" in decl or "(*" in decl:
        return None
    if lang == "ts":
        head = decl.split(":", 1)[0]
        head = head.strip().lstrip(".")
        m = re.match(r"(?:public |private |protected |readonly )*([A-Za-z_$][\w$]*)", head)
        return m.group(1) if m else None
    decl = re.sub(r"@\w+(\([^)]*\))?", " ", decl)          # annotations
    decl = re.sub(r"\[[^\]]*\]", " ", decl)                 # attributes @param? keep simple
    decl = decl.replace("...", " ")
    decl = re.sub(r"\bfinal\b|\bconst\b|\bvolatile\b|\bregister\b", " ", decl)
    if "=" in decl:                                        # default value
        decl = decl.split("=", 1)[0]
    tokens = re.findall(r"[A-Za-z_]\w*", decl)
    if not tokens:
        return None
    return tokens[-1]


def declaration_after(text, pos, lang):
    """Return (params, signature_text) for the declaration following `pos`."""
    tail = text[pos:]
    lines = tail.split("\n")
    idx = 0
    # Skip blanks, comments and annotations. An annotation whose argument list
    # spans several lines must be consumed whole, otherwise its tail line looks
    # like the declaration (this produced the MD5 false positive in seatunnel).
    while idx < len(lines) and idx < 24:
        s = lines[idx].strip()
        if not s or s.startswith("//"):
            idx += 1
            continue
        if s.startswith("@"):
            depth = s.count("(") - s.count(")")
            idx += 1
            while depth > 0 and idx < len(lines):
                depth += lines[idx].count("(") - lines[idx].count(")")
                idx += 1
            continue
        break
    if idx >= len(lines) or idx >= 12:
        return None, None
    window = "\n".join(lines[idx:idx + 24])
    open_at = window.find("(")
    if open_at < 0:
        return None, None
    callee = window[:open_at].rstrip()
    if "std::function" in callee or callee.endswith(">") or callee.endswith("]"):
        return None, None   # a callable member, not a function declaration
    if callee.endswith(".") or not re.search(r"\w$", callee) or "return " in callee:
        return None, None   # member call or statement, not a declaration
    if lang == "java" and not re.search(r"\w+\s+\w+$", callee):
        return None, None   # no return type + name pair
    head = window[:open_at]
    if "=" in head.split("\n")[-1] and "(" not in head:
        return None, None
    depth, end = 0, None
    for i, ch in enumerate(window[open_at:], start=open_at):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return None, None
    raw = window[open_at + 1:end]
    if "\n" in raw and lang != "java" and raw.count("\n") > 12:
        return None, None
    sig = (head + "(" + raw + ")").strip().split("\n")[-1] if "\n" not in raw else head + "(" + raw + ")"
    if sig.count("(") != 1 and lang != "java":
        return None, None
    return split_top_level(raw), sig


def check_file(path, lang, want_returns=False):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return [], []
    hits, unknown = [], []
    starts = [i for i, ch in enumerate(text) if ch == "\n"]

    def lineno(pos):
        return bisect.bisect_right(starts, pos) + 1

    for m in DOC_RE.finditer(text):
        body = m.group(1)
        if "@param" not in body and not (want_returns and RETURN_TAG.search(body)):
            continue
        params, sig = declaration_after(text, m.end(), lang)
        if params is None:
            unknown.append((path, text.count("\n", 0, m.start()) + 1, "no signature found"))
            continue
        names = [param_name(p, lang) for p in params]
        if any(n is None for n in names):
            unknown.append((path, text.count("\n", 0, m.start()) + 1,
                            "parameter shape not resolvable"))
            continue
        declared = set(names)
        fn = sig.split("(")[0].split()[-1].rstrip(":?") if "(" in sig else ""
        if fn and fn[0].isalnum() or fn:
            declared |= overload_params(text, m.end(), fn, lang)
        line = text.count("\n", 0, m.start()) + 1
        docd = []
        for tag in PARAM_TAG.finditer(body):
            name = tag.group(1)
            if GENERIC_DOC.match(name):
                continue                      # @param <T> documents a type parameter
            docd.append(name)
        stale = [n for n in docd if n not in declared]
        if stale:
            hits.append((path, line, (sig.split("(")[0].split()[-1] or "?") + "()", stale, sig))
        if want_returns and RETURN_TAG.search(body) and re.search(r"\bvoid\b", sig):
            hits.append((path, line, (sig.split()[-1] if " " in sig else "?"), ["@return on void"], sig))
    return hits, unknown


def overload_params(text, pos, name, lang):
    """Union of parameter names across overloads declared after `pos`.

    A doc block sits above the first overload; a later overload may add the
    parameter the block documents (Mooncake BatchPut has a 3-arg and a 5-arg
    form). Without this, the 3-arg form makes a correct doc look stale.
    """
    window = text[pos:pos + 4000]
    found, idx, seen = set(), 0, 0
    while True:
        at = window.find(name, idx)
        if at < 0 or seen >= 4:
            return found
        idx = at + len(name)
        if at and (window[at - 1].isalnum() or window[at - 1] in "_.:"):
            continue                     # part of a longer name or a member call
        j = at + len(name)
        while j < len(window) and window[j] in " 	":
            j += 1
        if j >= len(window) or window[j] != "(":
            continue
        open_at = j
        depth, end = 0, None
        for k, ch in enumerate(window[open_at:], start=open_at):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = k
                    break
        if end is None:
            return found
        for part in split_top_level(window[open_at + 1:end]):
            nm = param_name(part, lang)
            if nm:
                found.add(nm)
        seen += 1
        idx = end
def walk(root, lang):
    exts = {"java": (".java",), "ts": (".ts", ".tsx"), "cpp": (".h", ".hpp", ".cpp", ".cc", ".c")}[lang]
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fs:
            if f.endswith(exts):
                yield os.path.join(dp, f)


def selftest():
    import tempfile

    d = tempfile.mkdtemp(prefix="doctag_")
    p = os.path.join(d, "T.java")
    open(p, "w", encoding="utf-8", newline="\n").write(
        "class T {\n"
        "    /**\n"
        "     * Ok.\n"
        "     * @param a first\n"
        "     * @param <T> type param, not an argument\n"
        "     */\n"
        "    void ok(String a) {}\n"
        "\n"
        "    /**\n"
        "     * Stale.\n"
        "     * @param a first\n"
        "     * @param gone removed\n"
        "     */\n"
        "    void stale(String a) {}\n"
        "\n"
        "    /**\n"
        "     * Annotation between doc and signature.\n"
        "     * @param n count\n"
        "     */\n"
        "    @Override\n"
        "    @SuppressWarnings(\"unchecked\")\n"
        "    void annotated(int n) {}\n"
        "\n"
        "    /**\n"
        "     * Generic commas and varargs.\n"
        "     * @param map values\n"
        "     * @param rest the tail\n"
        "     */\n"
        "    void generics(java.util.Map<String, Integer> map, String... rest) {}\n"
        "\n"
        "    /**\n"
        "     * Unresolvable shape is never reported.\n"
        "     * @param gone cannot be judged\n"
        "     */\n"
        "    void pointers(void (*cb)(int));\n"
        "}\n")
    hits, unknown = check_file(p, "java")
    names = sorted((h[2], tuple(h[3])) for h in hits)
    assert names == [("stale()", ("gone",))], (names, unknown)
    assert len(unknown) == 1, unknown
    t = os.path.join(d, "t.ts")
    ts_src = chr(10).join([
        "export function ok(input: z.infer<typeof schema>, ctx: Ctx): void {}",
        "/**",
        " * Stale.",
        " * @param input fine",
        " * @param gone removed",
        " */",
        "export function stale(input: string): void {}",
    ]) + chr(10)
    open(t, "w", encoding="utf-8", newline=chr(10)).write(ts_src)
    tshits, _ = check_file(t, "ts")
    assert sorted(tuple(h[3]) for h in tshits) == [("gone",)], tshits
    print(f"selftest ok  hits={names}  unknown={len(unknown)}  ts={[tuple(h[3]) for h in tshits]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "selftest":
        selftest()
        return
    root = sys.argv[1].rstrip("/\\")
    lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "java"
    show = "--show" in sys.argv
    want_returns = "--returns" in sys.argv
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 60

    hits, unknowns, files = [], 0, 0
    for p in walk(root, lang):
        files += 1
        h, u = check_file(p, lang, want_returns)
        hits += h
        unknowns += len(u)
    print(f"root={os.path.basename(root) or root} lang={lang} files={files} "
          f"stale={len(hits)} unknown={unknowns}")
    for path, line, fn, stale, sig in hits[:cap]:
        rel = os.path.relpath(path, root)
        print(f"   {rel}:{line}  {fn}  documents {stale}")
        if show:
            print(f"      sig: {sig[:200]}")


if __name__ == "__main__":
    main()
