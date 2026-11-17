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

## False positives this project refuses to ship

- A parameter the body reads out of `**kwargs` is not stale.
- A docstring that documents nothing is not an error; only a mismatch is.
- A dead link inside archived meeting minutes is not a defect — rewriting history is not a fix.
- A URL that answers 404 to `HEAD` and 200 to `GET` is alive; probe with a browser `GET` before
  reporting.

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
