[![ci](https://github.com/lxcxjxhx/doc-drift/actions/workflows/ci.yml/badge.svg)](https://github.com/lxcxjxhx/doc-drift/actions/workflows/ci.yml)

# doc-drift

Small checkers that find **documentation that has stopped being true**: docstrings describing
parameters the function no longer takes, links whose fragment matches no heading, examples
importing symbols the package no longer exposes.

Every checker here is stdlib-only Python 3.9+, takes a directory, and prints findings with
`file:line`. No dependencies, no configuration, no daemon.

```console
$ python tools/run_all.py /path/to/repo        # every portable checker, one table
$ python tools/docstring_check.py /path/to/repo
$ python tools/anchor_check.py /path/to/docs --max 30
$ python tools/docs_links.py /path/to/repo --only-prefix docs
```

`run_all.py` prints a table with the finding count, the wall time and each checker's own summary
line, and it refuses to guess arguments: the two placeholder tools need a repository-specific
locale layout, so they are listed as *not run* unless you pass `--all`.

## Try it on your repository

Three commands, no dependencies, nothing installed:

```console
$ git clone --depth 1 https://github.com/lxcxjxhx/doc-drift
$ cd doc-drift
$ python tools/run_all.py /path/to/your/repo
```

A run against this repository itself, trimmed:

```
| checker | findings | summary |
|---|---:|---|
| docstrings | 1 | root=doc-drift  files=16  stale-args=1 |
| doc/code tokens | 0 | docs=1 code=17 env-not-in-code=0 flags-not-in-code=5 |
| md duplicates | 0 | files-with-dup-heading=0  ...  repeated-under-different-parents=0 |
| doc commands | 0 | commands-in-docs=0 not found in a manifest |
```

The one finding is deliberate: `fixtures/` contains a stale docstring so a parser regression shows
up as a red build rather than as a quiet false negative.

**Reading the result.** A `0` means "ran and found nothing"; the summary column is there so you can
tell that apart from "did not look" (e.g. `no locale pair found` means the bilingual checkers had
nothing to compare). `not run` lists the two checkers that need repository-specific arguments —
`--all` opts in.

**Focus a check.** Each tool also runs alone, and the two that walk whole trees take a path filter:

```console
$ python tools/docstring_check.py path/to/pkg            # one package
$ python tools/docs_links.py . --only-prefix docs        # only links into docs/
$ python tools/docs_task_refs.py . --show                # every make/npm/compose reference
```

## What each one finds

| Tool | Finding |
|---|---|
| `docstring_check.py` | docstring `Args:`/`Returns:` entries for parameters or return values the function cannot have — the usual residue of a rename or a signature change |
| `docstring_triage.py` | classifies those findings into real drift vs `**kwargs`-ambiguous, so the report is actionable rather than a list to re-check by hand |
| `doctag_check.py` | the same class in doxygen `@param` tags (C/C++/JSDoc-style) |
| `anchor_check.py` | `#fragment` in a markdown link that matches no heading anchor, including the emoji-heading double-dash case |
| `docs_links.py` | relative links in `md`/`rst`/`mdx` that resolve to nothing, with an optional path filter |
| `docs_parity.py` | pages that exist in one language tree but not the other (bilingual docs drift) |
| `docs_code_refs.py` | Python snippets in docs that import a symbol the package no longer exposes |
| `docs_code_tokens.py` | environment variables, CLI flags and config keys named in docs but absent from the code — and the reverse |
| `locale_placeholders.py` | a translated string that lost a `{placeholder}`, which renders literally in the UI — works on TS/JS object-literal locale files and on JSON |
| `i18n_placeholders.py` | the same comparison for a JSON locale directory laid out one namespace per file (the Next.js `i18n/<locale>/<ns>.json` shape) |
| `i18n_placeholders.py` | the same comparison across a JSON locale directory (one namespace per file) |
| `md_table_check.py` | table rows whose cell count differs from the header, which renders as a broken table |
| `docs_task_refs.py` | `make <target>`, `npm run <script>` and `docker compose <cmd> <service>` lines whose target does not exist in the repository's Makefile, `package.json` scripts or compose file |
| `md_lint.py` | four leftover dimensions: fenced blocks without a language tag (judged against the repo's own convention), the same heading repeated inside one file (which makes `#slug` ambiguous), a localized page whose heading structure drifted from its counterpart, and structure that translation never removes (code blocks, tables, images, source links) |

## The method, since it is the point

A checker is worth nothing until you know its false-positive rate, so each one was validated the
same way:

1. **Replay merged PRs.** Run the checker against the commit *before* a documentation-fix PR was
   merged and confirm it reports exactly that fix — and nothing else in the same file.
2. **Triage what is left.** Every remaining hit is read. If it is deliberate (a `**kwargs` reader, a
   `noqa` with a stated reason, a templated example URL), the checker gets a filter or the finding is
   recorded as a false positive with the reason.
3. **Silence is a result.** A clean run on a mature repository is written down as such, because the
   next person needs to know the dimension was checked, not skipped.

`fixtures/` holds the two shapes that caused the most trouble — a Google-style docstring and a
NumPy-style one — so a regression in the parser shows up as a failing fixture rather than as a quiet
false negative.

Every checker also ships `selftest`, which asserts **both directions**: the defect it exists to find,
and the near-miss it must stay quiet about (a `**kwargs` name that is read back, a table inside a
fenced block, a token that only appears inside a URL, a key whose placeholders merely reorder).
Run them all:

```console
$ for f in tools/*.py; do grep -q '^def selftest' "$f" && python "$f" selftest; done
```

## False positives this project refuses to ship

- A parameter the body reads out of `**kwargs` is not stale.
- A docstring that documents nothing is not an error; only a mismatch is.
- A dead link inside archived meeting minutes is not a defect — rewriting history is not a fix.
- A URL that answers 404 to `HEAD` and 200 to `GET` is alive; probe with a browser `GET` before
  reporting.
- A link into a tree the site *generates* (`docs/api/` from mkdocstrings) or *stages* before
  building (`i18n/<code>/pages/`) points at a page that exists in the output and not in the
  checkout. Both are skipped by path.
- A migration guide or changelog names the symbols and module paths it is telling you to move
  away from; those pages are not scanned for stale imports.
- A flag that belongs to another program (`gh release create --notes-file`, `pip install
  --force-reinstall`, `uvicorn --forwarded-allow-ips`) cannot be resolved from this repository.
- The same sub-heading under *different* parents is a repeated structure, not an ambiguous anchor:
  one `#### Pros` per option in an ADR (32 groups in agent-framework), one `Key Requirements:` per
  integration, one `### Fixed` per release. Only a repeat inside the same section is reported.
- Two headings the author already disambiguated — a table of contents linking `#usage` **and**
  `#usage-1` — are counted separately as `acknowledged-by-anchor`.
- A template (`adr-template.md`, `spec-template.md`) links a numbered document that does not exist
  yet; that link is the template's shape, not a broken reference.

## Measured on real repositories

Fourteen checkers, run against six repositories in three ecosystems (C, Python, TypeScript). A `0`
means "ran and found nothing", which is the only way to tell that apart from "did not look".

| repository | first pass | after triage | what happened |
|---|---:|---:|---|
| `vanhauser-thc/thc-hydra` | 0 | 0 | — |
| `pytorch/torchtitan` | 1 | 0 | duplicate heading the document's own ToC already disambiguates |
| `modelcontextprotocol/python-sdk` | 80 | 0 | generated `docs/api/` tree, staged `i18n/` trees, and a migration guide that names old paths |
| `vllm-project/llm-compressor` | 4 | 0 | one real (**PR #3526**), plus headings repeated under different parents |
| `microsoft/agent-framework` | 42 | 0 | one real (**PR #10400**), plus 32 structural repeats and 3 template placeholder links |
| `pipecat-ai/pipecat` | 9 | 0 | `CHANGELOG` release headings |

(One observation, dated 2026-11-17 — the figures above are a snapshot, not a live count; the two checkers
that produce them are in the campaign repository, not here.)

Two upstream fixes came out of this table, and both are the same size: a table row with four cells
under a three-column header, and a heading written twice in a row. The rest of the 136 first-pass
findings were the checker being wrong, and each one changed the checker rather than the repository.

That ratio is the honest headline. A rule that only ever finds things is not measuring; it is
guessing. What makes these usable is that every false-positive class above is now a named rule with
a fixture, so the next repository hits it deliberately instead of by accident.

## What this is not

Not a linter substitute and not a documentation grader: it reports *contradictions between a
document and the code beside it*, which no style linter looks at. It will not tell you the prose is
bad, only that it names something that no longer exists.

It also has no opinion about your project's conventions — where a checker depends on one (the
fence-tagging rule), it measures the repository against itself rather than against a fixed threshold.

## Provenance

Extracted from a campaign of 480 upstream pull requests, 86 of them merged across 39 repositories
(`gh search prs --author @me --merged`). The campaign's private ledger is not shipped here; what is
shipped is the method and the checkers it produced.
