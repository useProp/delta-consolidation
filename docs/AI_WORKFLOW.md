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

## Not done yet

- The plan's independent review — a fresh session without the implementation context, given `docs/SPEC.md` and the code, looking for discrepancies in the elimination and translation logic — has not been run.
