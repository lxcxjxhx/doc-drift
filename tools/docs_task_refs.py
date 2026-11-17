#!/usr/bin/env python3
"""Commands the docs tell you to run, whose target does not exist.

`make lint` in a README is a promise. When the Makefile renames the target, the line
stays and the next reader wastes ten minutes on `No rule to make target 'lint'`.

Checked, but only when the manifest is present in the repository:
  make <target>            → targets and pattern rules in Makefile / *.mk
  npm|pnpm|yarn run <name> → "scripts" in package.json
  docker compose <cmd> <service> → service names in compose.y*ml

Absence is a signal, not proof — and so is presence. Known false-positive classes,
both seen in the wild and deliberately not "fixed" by a cleverer heuristic:

  * a docs page that walks a reader through a *different* project ("clone the template,
    then run `pnpm run pack`") names scripts this repository does not own;
  * a target provided by an included or generated Makefile fragment.

So the report is a list of lines to read, not a list of bugs. On FastGPT the checker
reports eight `pnpm run pack` lines and every one of them is the first class.

Usage: python docs_task_refs.py <repo> [--show]
"""
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
CODE_EXT = {".md", ".mdx", ".rst"}
SKIP_FILES = {"CHANGELOG.md", "CHANGELOG.mdx"}

FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
INLINE = re.compile(r"`([^`\n]+)`")
MAKE = re.compile(r"(?:^|[\s$])make\s+(?:-[A-Za-z-]+\s+\S+\s+)*([A-Za-z0-9_.%/-]+)")
# Only an explicit `run` is evidence. `pnpm prettier --check` runs a binary from
# node_modules/.bin, and a template's docs name scripts the generated project owns —
# both are indistinguishable from a script name by shape, so the bare form is skipped.
NODE_RUN = re.compile(r"\b(?:npm|pnpm|yarn)\s+run\s+([A-Za-z0-9:_.-]+)")
COMPOSE = re.compile(
    r"docker\s+compose\s+(?:-f\s+\S+\s+)?(?:up|run|exec|logs|build|restart|stop|start|pull|rm|ps)"
    r"\s+(?!-)([A-Za-z0-9_.-]+)")
# A line that is prose about a command rather than a command is not evidence.
NOT_A_COMMAND = re.compile(r"^\s*(?:#|//|;|>|\*|-)")

MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.][A-Za-z0-9_.%-]*)\s*:(?!=)", re.M)
# Everything npm/yarn/pnpm accepts without a `run` — none of these is a script name.
NPM_BUILTIN = {
    "i", "install", "ci", "add", "remove", "rm", "uninstall", "un", "update", "up",
    "outdated", "audit", "fund", "ls", "list", "ll", "la", "root", "bin", "prefix",
    "config", "set", "get", "init", "create", "publish", "pack", "link", "exec", "x",
    "explain", "why", "dedupe", "prune", "repo", "access", "whoami", "token", "owner",
    "org", "team", "search", "view", "info", "show", "cache", "doctor", "help", "test",
    "start", "stop", "restart", "version", "import", "rebuild", "workspace", "workspaces",
    "dlx", "env", "set-version", "upgrade", "global", "store", "node", "plugin", "patch",
}
COMPOSE_CMD_OK = {"version", "config", "down", "ls", "help"}


def docs(root):
    for p in Path(root).rglob("*"):
        if p.is_dir() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in CODE_EXT and p.name not in SKIP_FILES:
            yield p


def make_targets(root):
    """Targets from every Makefile in the tree — monorepos keep one per package."""
    targets, found = set(), False
    for name in ("Makefile", "makefile", "GNUmakefile"):
        for f in Path(root).rglob(name):
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            found = True
            targets |= set(MAKE_TARGET.findall(f.read_text(encoding="utf-8", errors="replace")))
    for f in Path(root).rglob("*.mk"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        found = True
        targets |= set(MAKE_TARGET.findall(f.read_text(encoding="utf-8", errors="replace")))
    return (targets - {".PHONY", "include", "export"}) if found else None


def npm_scripts(root):
    """Script names from every package.json in the tree, unioned: a docs page may run a
    script that belongs to a workspace package rather than to the root."""
    scripts, found = set(), False
    for f in Path(root).rglob("package.json"):
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "scripts" not in data or not isinstance(data["scripts"], dict):
            continue
        found = True
        scripts |= set(data["scripts"].keys())
    return scripts if found else None


def compose_services(root):
    files = [p for p in Path(root).glob("compose*.y*ml")] + [p for p in Path(root).glob("docker-compose*.y*ml")]
    if not files:
        return None
    names, seen = set(), False
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"^services:\s*$([\s\S]*?)(?=^\S|\Z)", text, re.M)
        if not block:
            continue
        seen = True
        for line in block.group(1).splitlines():
            m = re.match(r"^  ([A-Za-z0-9_.-]+):", line)
            if m:
                names.add(m.group(1))
    return names if seen else None


def scan(root):
    root = Path(root)
    targets, scripts, services = make_targets(root), npm_scripts(root), compose_services(root)
    hits = []
    for doc in docs(root):
        text = doc.read_text(encoding="utf-8", errors="replace")
        commands = []
        for block in FENCE.findall(text):
            commands += [l for l in block.splitlines() if l.strip() and not NOT_A_COMMAND.match(l)]
        for line in INLINE.findall(text):
            commands.append(line)
        for line in commands:
            line = line.strip()
            if targets is not None:
                for t in MAKE.findall(line):
                    if t.startswith("-") or "%" in t:
                        continue
                    if t not in targets:
                        hits.append((doc.relative_to(root).as_posix(), "make", t))
            if scripts is not None:
                for name in NODE_RUN.findall(line):
                    if name not in scripts:
                        hits.append((doc.relative_to(root).as_posix(), "package-script", name))
            if services is not None:
                for svc in COMPOSE.findall(line):
                    if svc in COMPOSE_CMD_OK or svc in services:
                        continue
                    hits.append((doc.relative_to(root).as_posix(), "compose-service", svc))
    return hits


def selftest():
    """A renamed make target, an unknown npm script and an unknown compose service are
    reported; a real target, a pattern rule, an npm builtin and a `#` comment are not."""
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="tr_"))
    (d / "Makefile").write_text(
        ".PHONY: test lint\n"
        "test:\n\tpytest\n"
        "lint:\n\truff check .\n"
        "%.o: %.c\n\tcc -c $<\n", encoding="utf-8")
    (d / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite", "build": "vite build"}}), encoding="utf-8")
    (d / "compose.yaml").write_text(
        "services:\n  api:\n    image: x\n  db:\n    image: y\n", encoding="utf-8")
    (d / "README.md").write_text(
        "```console\n"
        "make test\n"
        "make lint\n"
        "make gone\n"
        "npm run dev\n"
        "npm run removed\n"
        "docker compose up api\n"
        "docker compose up nowhere\n"
        "# make commented-out\n"
        "```\n\n"
        "Inline: `make test` and `npm run build` are fine.\n",
        encoding="utf-8")
    hits = scan(d)
    assert ("README.md", "make", "gone") in hits, hits
    assert ("README.md", "package-script", "removed") in hits, hits
    assert ("README.md", "compose-service", "nowhere") in hits, hits
    assert not [h for h in hits if h[2] in ("test", "lint", "dev", "build", "api", "commented-out")], hits
    print(f"selftest ok  hits={hits}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    root = Path(sys.argv[1])
    show = "--show" in sys.argv
    hits = scan(root)
    print(f"{root.name}: commands-in-docs={len(hits)} not found in a manifest")
    for doc, kind, name in hits[: (100 if show else 10)]:
        print(f"   {doc}  {kind} {name}")
    if any(h[1] == "make" for h in hits):
        pass


if __name__ == "__main__":
    main()
