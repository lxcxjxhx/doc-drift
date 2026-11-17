# A submission note for the Security Tooling WG

> One page, written to be read by someone who has not seen this repository before.
> Every number below can be recomputed with a command that is given next to it.

## What this is

`doc-drift` is fourteen small checkers that find places where a **security or engineering document
has stopped being true about the code or guidance beside it** — and reports nothing when the
checkout does not contain enough information to judge.

It is not a prose linter and not a style guide. It answers one question: *does this sentence still
name something that exists?*

## Why a tooling WG might care

Documentation drift in security work is not cosmetic. The failures this tool was built against are:

- **a citation that points at guidance which has been archived or withdrawn** — the reader follows a
  link to a page that no longer says what the sentence claims;
- **a documented flag, env var or symbol that the code no longer has** — the reader runs a command
  that fails, in a procedure they are following under pressure;
- **a translated page that has silently fallen behind** — the wrong instructions are the ones the
  reader can actually read.

The first is exactly the class fixed in
[`wg-security-tooling#71`](https://github.com/ossf/wg-security-tooling/pull/71) (four citations
pointed at their archived copies); [`#72`](https://github.com/ossf/wg-security-tooling/pull/72)
is the same class in the SBOM section.

## Evidence that it works, and that it stays quiet

```console
$ git clone --depth 1 https://github.com/lxcxjxhx/doc-drift && cd doc-drift
$ python tools/run_all.py --selftest
selftest ok  ran=14
```

Every checker carries a self-test asserting **both** directions: the defect it exists to find, and
the near-miss it must *not* report. That second half is what makes the output usable.

Validation was against six real repositories in three ecosystems, not fixtures:

| repository | first pass | after triage | what the findings actually were |
|---|---:|---:|---|
| `vanhauser-thc/thc-hydra` | 0 | 0 | — |
| `pytorch/torchtitan` | 1 | 0 | duplicate heading its own ToC already disambiguates |
| `modelcontextprotocol/python-sdk` | 80 | 0 | generated `docs/api/` tree, staged `i18n/` tree, a migration guide that names old paths |
| `vllm-project/llm-compressor` | 4 | 0 | one real (table row: 4 cells under a 3-column header) |
| `microsoft/agent-framework` | 42 | 0 | one real (a heading written twice in a row) |
| `pipecat-ai/pipecat` | 9 | 0 | changelog release headings |

**136 first-pass findings, two real, both filed upstream.** The other 134 changed the checker.
That ratio is the point of the next section.

## The part that matters for adoption: named false-positive classes

Ten classes are written down in the README with the repository that produced each, because a checker
that only ever finds things is guessing. Examples:

- a link into a tree the site *generates* (`docs/api/`) or *stages* (`i18n/<code>/`) exists in the
  output and not in the checkout;
- a migration guide **must** name the symbols it is telling you to move away from;
- a flag belonging to another program (`gh`, `pip`, `uvicorn`) cannot be resolved from the repository;
- the same sub-heading under different parents is a structure (one `#### Pros` per option in an ADR),
  not an ambiguous anchor.

Each class has a fixture, so a later change to the filter cannot silently pass.

## Limits, stated plainly

- It judges **existence, not truth**: it can tell you a symbol was removed, not that a paragraph is
  wrong about policy.
- Rendered-anchor checks depend on the renderer; GitHub, Mintlify, MkDocs `attr_list` and Sphinx
  differ, and the tool dispatches by path where it can and says so where it cannot.
- It needs a full checkout. A sparse or filtered clone makes "the file is missing" indistinguishable
  from "the file is not there", so link checks are unreliable on one.
- Python docstring checks are AST-based and count what they cannot parse as `unknown`, printed next
  to every hit list. A run with many unknowns is not evidence.

## The ask

If documentation drift is in scope for the WG's tooling inventory, is `doc-drift` worth listing as a
candidate, and where? If it is not in scope, a sentence saying so is equally useful — I would rather
know than keep polishing something the WG does not need.

If a demonstration is more useful than a description, the fastest one is the command above against
any repository in the list, plus `python tools/docs_links.py <repo> --only-prefix docs` for the single
checker most likely to find something real in a docs tree.
