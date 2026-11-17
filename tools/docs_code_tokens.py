#!/usr/bin/env python3
"""Cross-check tokens a README/docs mention against the code tree.

Two classes, both cheap and both used for real finds in this campaign:
  * ALL_CAPS names in backticks that look like env vars (FOO_BAR) — does the
    code read them anywhere?
  * `--flag` CLI flags — does any source file or shell script mention them?

Reported as "documented, not found in code". Absence is a signal, not proof:
generated code, docs for external binaries and shell wrappers all produce
legitimate misses, so every hit needs a manual read before it becomes an issue.

usage: python pr-work/_tools/docs_code_tokens.py <repo> [--show]
"""
import re
import sys
from pathlib import Path

SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "third-party", "third_party"}
# Changelogs mention flags/env vars from *past* releases, and agent-skill docs
# describe the dev workflow, not the product. Both produce pure noise (20 env
# hits in pipecat were all CHANGELOG history), so they are not evidence.
SKIP_FILES = {"CHANGELOG.md", "CHANGELOG.mdx", "CHANGELOG.rst"}
# Agent/skill docs describe the dev workflow, not the product; testdata is fixture
# input (cli/cli's `.github/skills/**` produced 5 pure-noise flag rows).
SKIP_DIR_PARTS = {".claude", ".agents", "agents", "skills", "testdata"}
# A real env var is SCREAMING_SNAKE. Tokens without an underscore are scheme or
# format names in prose (`MXFP6A16`, `MXFP8`) and produced 7 false "missing env
# var" rows in llm-compressor's compression_schemes.md.
ENV = re.compile(r"`([A-Z][A-Z0-9]*_[A-Z0-9_]{2,})`")
FLAG = re.compile(r"`?(--[a-z][a-z0-9-]{2,})`?")
# Build-system files carry env-var reads too (CMake `if(DEFINED FOO)`, patch
# workflows), and Go's cobra declares flags as plain strings: `Flags().Bool("x"`.
CMAKE_NAMES = {"CMakeLists.txt"}
CODE_EXT = {".py", ".c", ".cc", ".cpp", ".cu", ".h", ".hpp", ".rs", ".sh", ".js", ".ts", ".java", ".go", ".toml", ".yaml", ".yml", ".cfg"}


def walk(root, exts):
    for p in Path(root).rglob("*"):
        if p.is_dir() or any(part in SKIP for part in p.parts):
            continue
        if p.name in SKIP_FILES or any(part in SKIP_DIR_PARTS for part in p.parts):
            continue
        if p.suffix in exts or p.name in CMAKE_NAMES:
            yield p


def scan(root):
    """Return (env-not-in-code, flag-not-in-code) as {token: first doc that mentions it}."""
    root = Path(root)
    docs = [p for p in walk(root, {".md", ".mdx", ".rst"})]
    code_files = list(walk(root, CODE_EXT))
    code = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in code_files
    )
    declared = set(re.findall(r'Flags?\(\)\.[A-Za-z]+\(\s*"([a-z][a-z0-9-]+)"', code))
    env_seen, flag_seen = {}, {}
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="replace")
        for name in ENV.findall(text):
            if name in {"README", "MIT", "APACHE", "GPU", "CPU", "API", "URL", "HTTP",
                        "HTTPS", "JSON", "YAML", "TRUE", "FALSE", "NONE"}:
                continue
            if name not in code:
                env_seen.setdefault(name, doc.relative_to(root).as_posix())
        no_urls = re.sub(r"https?://\S+", "", text)
        for flag in FLAG.findall(no_urls):
            if flag.lstrip("-") in declared:
                continue
            if flag not in code:
                flag_seen.setdefault(flag, doc.relative_to(root).as_posix())
    return env_seen, flag_seen


def selftest():
    """A token the code never reads is reported; a token it does read, one declared as a
    cobra string, and one that only appears inside a URL are not."""
    import tempfile

    d = tempfile.mkdtemp(prefix="dct_")
    (Path(d) / "README.md").write_text(
        "Set `MISSING_VAR` to enable it, or `KNOWN_VAR` to keep it.\n"
        "Run `--gone-flag` to break, `--known-flag` to work, `--declared-flag` too.\n"
        "Docs: https://example.com/page#libraries--sdks\n",
        encoding="utf-8",
    )
    (Path(d) / "app.py").write_text(
        "import os\nos.environ['KNOWN_VAR']\nparser.add_argument('--known-flag')\n"
        "parser.Flags().Bool(\"declared-flag\", False)\n",
        encoding="utf-8",
    )
    env, flag = scan(d)
    assert list(env) == ["MISSING_VAR"], env
    assert list(flag) == ["--gone-flag"], flag
    print(f"selftest ok  env={list(env)} flags={list(flag)}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    root = Path(sys.argv[1])
    show = "--show" in sys.argv
    docs = [p for p in walk(root, {".md", ".mdx", ".rst"})]
    code_files = list(walk(root, CODE_EXT))
    code = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in code_files
    )
    # Flags declared as API strings (cobra/pflag: Flags().Bool("hidethinking")) are
    # real flags but never appear as `--name` in source.
    declared = set(re.findall(r'Flags?\(\)\.[A-Za-z]+\(\s*"([a-z][a-z0-9-]+)"', code))
    env_seen, flag_seen = {}, {}
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="replace")
        for name in ENV.findall(text):
            if name in {"README", "MIT", "APACHE", "GPU", "CPU", "API", "URL", "HTTP",
                        "HTTPS", "JSON", "YAML", "TRUE", "FALSE", "NONE"}:
                continue
            if name not in code:
                env_seen.setdefault(name, doc.relative_to(root).as_posix())
        # URLs contain `--` in fragments (…readme#libraries--sdks) and are not flags.
        no_urls = re.sub(r"https?://\S+", "", text)
        for flag in FLAG.findall(no_urls):
            if flag.lstrip("-") in declared:
                continue
            if flag not in code:
                flag_seen.setdefault(flag, doc.relative_to(root).as_posix())
    print(f"{root.name}: docs={len(docs)} code={len(code_files)} "
          f"env-not-in-code={len(env_seen)} flags-not-in-code={len(flag_seen)}")
    for label, table in (("env", env_seen), ("flag", flag_seen)):
        for name, src in sorted(table.items()):
            if show:
                print(f"  {label} {name:<34} first seen in {src}")


if __name__ == "__main__":
    main()
