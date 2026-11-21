# AI workflow

## Tools and roles

| Phase | Tool | Who decided |
| --- | --- | --- |
| Reading the task, plan, assumptions, elimination and translation rules, demo data, oracle, expected figures | Claude in a claude.ai chat (19–21 Nov 2026), see [`PLANNING_LOG.md`](PLANNING_LOG.md) | The human set the goals and reviewed the plan; the AI drafted it and checked Odoo behaviour against the 18.0/19.0 source |
| Implementation, tests, UI check, documentation | Claude Code (Opus) in this repository, following [`PLAN.md`](PLAN.md) section 6 step by step and the rules in [`../CLAUDE.md`](../CLAUDE.md) | The agent wrote the code; decisions that changed the plan's behaviour were put to the human (see below) |

## What was fixed before code

The agent could not move the target:

1. Assumptions, rules and the demo data were written first, in `docs/`.
2. `docs/oracle.py` (plain Python, no Odoo) computed the expected figures and committed them with the seeds' sha256. `CLAUDE.md` forbids editing `expected_figures.json` by hand and says a mismatch is a reason to stop and investigate, never to change the expectations.
3. Tests contain no numbers: they read the seeds and the expected-figures file.

## How each step was run

- One plan step = one slice: its tests against `expected_figures.json` first, then the code until green, then the full suite (previously green tests stay green), then a commit. Seven commits, one per step.
- Every step ended with `docker compose run --rm test` exit 0 and `python docs/oracle.py --check` exit 0.
- Before relying on exit codes, the agent made a test fail on purpose to confirm a red run exits 1; later it corrupted one expected figure (CTA) to confirm the balance-sheet test catches it, and removed a fix to confirm its new test fails without it.
- Odoo behaviour was checked in the source inside the `odoo:18.0` image, not from memory.

## Where the plan or the agent was wrong, and what caught it

| Problem | Caught by | Resolution |
| --- | --- | --- |
| Loading `generic_coa` sets the company's currency and country to the US ones, so UAH and PLN companies would become USD companies | Reading `chart_template.py` in the image before writing the loader | Loader restores the currency and clears the country (ASSUMPTIONS.md) |
| Posting a credit note with `reversed_entry_id` auto-reconciles it with the invoice and books a PLN 200 exchange difference, which the plan excluded: Poland's March profit came out 67,400 instead of 67,200 | `test_demo_books` failing against the oracle's figures; then inspecting the journal items in the demo database | The agent stopped and asked; the human chose to link the credit note after posting, keeping the plan's figures |
| admin could not open the module at all: in Community admin lacks "Show Full Accounting Features" | Manual UI check in the browser — all tests were green | Loader grants the group; a test now checks it |
| The *Source* button failed when the active company was not the source document's company | Manual UI check | Source reference read via `sudo()`; the test now reproduces the UI situation and was shown to fail without the fix |
| The report's P&L total was income + expenses, and intercompany receivables shared a row with external ones | Manual UI check against the section 8 checklist | P&L lines carry the profit contribution; intercompany rows are labelled "(IC)"; tests assert both |
| A test referenced `partner` on documents that have none | The test run itself | Fixed the test, not the code |

Lesson: tests on the numbers were right from the first green run, but three of the issues above were invisible to them and showed up only when the result was used the way a reviewer would use it.

## Independent review

As the plan asks, a separate Claude Code session with no implementation context read `docs/SPEC.md`, the assumptions, the code and the oracle, without running anything, and reported 12 findings. Back in the implementation session, the human asked for the high and medium findings to be fixed. The agent wrote a regression test per finding together with the fix, then ran the new tests against the code before the fix (a temporary worktree at the previous commit) to confirm each one fails there; one test first failed there only on a missing method and was reshaped until it reproduced the real crash:

| Finding | Severity | Outcome |
| --- | --- | --- |
| Invoice section/note lines (no account, but the invoice partner) crash Generate and the report | High | Confirmed (`'bool' object has no attribute 'startswith'` in `_is_ic`); amount-less lines filtered |
| No company isolation: a one-company accountant sees all books of the group through the report | High | Confirmed; record rules plus an explicit check require access to all group companies |
| Exchange-difference lines on IC accounts are translated to 0 | Medium | Rejected with reasoning (ASSUMPTIONS.md); a reconciliation test now covers the scenario, which no test had before |
| Balance sheet takes all history, prior-year P&L lands in current year earnings, prior-year IC is not eliminated | Medium | Confirmed, shared by the oracle; "Retained earnings" split in both, eliminations from the first month with activity |
| Post locks a stale draft | Medium | Confirmed; Post regenerates |
| Reconciliation of a posted entry changes with the books | Medium-low | Confirmed; frozen on Post |
| The read-only auditor creates draft entries; report rows shared between users | Medium-low | Confirmed; unposted months computed on the fly, rows per user |
| Posted header editable, group deletion cascades, lines movable into a posted entry | Low | Confirmed; locked |
| Account code of elimination rows read in the wrong company | Low | Fixed (no dedicated test) |
| Transit attributed to the first counterparty; contacts of group partners not detected | Low | Not changed, recorded as out of scope |
| SPEC signatures and oracle order drifted | Low | Aligned |

The review was worth it: the two high findings were invisible to tests built on the demo data, because the demo has no section lines and only users with access to every company.
