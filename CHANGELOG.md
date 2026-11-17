# Changelog

All notable changes to the checkers. Every entry names the repository that produced it,
because a rule that was never tested against real code is a guess.

## v0.1.0 — 2026-11-17

First tagged release. Fourteen checkers, all stdlib-only, each with a `selftest` that
asserts both the defect and the near-miss it must stay quiet about.

**Checkers**

- `docstring_check` / `docstring_triage` / `doctag_check` — docstring and doc-tag
  parameter drift (Google and NumPy styles; doxygen tags).
- `anchor_check` / `docs_links` / `docs_parity` — markdown anchors, relative links, and
  bilingual page parity.
- `docs_code_refs` / `docs_code_tokens` — symbols a docs example imports, and env
  vars / flags the docs name.
- `docs_task_refs` — `make` targets, `package.json` scripts and compose services the docs
  tell you to run.
- `locale_placeholders` / `i18n_placeholders` — a translated string that lost a
  `{placeholder}`.
- `md_lint` (fence / dup / parity / struct) and `md_table_check`.
- `run_all.py` — one table over the set, and it refuses to guess repository-specific
  arguments.

**Validated against, not just written for**

| repository | first pass | after triage | outcome |
|---|---:|---:|---|
| `vanhauser-thc/thc-hydra` | 0 | 0 | — |
| `pytorch/torchtitan` | 1 | 0 | duplicate heading the ToC already disambiguates |
| `modelcontextprotocol/python-sdk` | 80 | 0 | generated `docs/api/`, staged `i18n/`, a migration guide |
| `vllm-project/llm-compressor` | 4 | 0 | one real (table row: 4 cells under a 3-column header) |
| `microsoft/agent-framework` | 42 | 0 | one real (heading written twice in a row) |
| `pipecat-ai/pipecat` | 9 | 0 | changelog release headings |

**Ten named false-positive classes**, each with the repository that produced it, live in
the README. `dup` alone learned three: a ToC that links `#slug` and `#slug-1` has already
disambiguated itself; the same sub-heading under different parents is a repeated structure
(an ADR with one `#### Pros` per option); and changelogs repeat `Added`/`Fixed` per release
by design.
