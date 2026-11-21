# Planning log

Planning happened in a claude.ai chat with Claude (19–21 Nov 2026), before any module code was written. Implementation continues in Claude Code. This log is the input for the planning part of `docs/AI_WORKFLOW.md`.

## What was done

1. Read the task (`docs/TASK.png`) and wrote the plan (`docs/PLAN.md`): assumptions, architecture, elimination and translation rules, demo data, steps with checks, tests, final checklist.
2. Checked Odoo behaviour against the source instead of memory: shallow clones of `odoo/odoo` (branches 18.0 and 19.0) and `odoo/docker`. Covered currency rate lookup, the invoice accounting date, when payments create journal entries, company creation and localisation install, chart loading, CLI flags, the test exit code and the official image entrypoint.
3. Wrote an independent oracle in plain Python (no Odoo) and computed the expected figures before implementation.
4. Moved all demo data into one seed file read by both the loader and the oracle. The oracle generates `expected_figures.json` and stores the seeds' sha256, so a stale file is detected.
5. Reviewed the whole plan for errors, then translated all documentation into English.

## What the human asked for

- A detailed implementation plan with explicit steps and a way to verify each one.
- A review of the plan for errors, with the fixes applied.
- Seeds and data samples, so that the project is ready to run as soon as the agent finishes implementing.
- All code, comments and documentation in English.
- Implementation in Claude Code, with this repository as the hand-off.

## Errors the review caught

| Problem in the draft | How it was caught | Fix |
| --- | --- | --- |
| `docker-compose.yml` used anonymous volumes: `docker compose run --rm` deletes the filestore after `demo`, and `down` loses the database | Review of the compose file against Docker volume behaviour | Named volumes `db-data` and `odoo-data` |
| The pivot total would sum amounts in UAH, PLN and USD | Review of the report model | `aggregator=None` on `amount_local` |
| A pitfall claimed `-i` does not reload an installed module and that `-u` is required | Reading `odoo/modules/graph.py` and `odoo/modules/loading.py` (18.0) | `-i` alone is enough; the pitfall was removed |
| Exchange-difference lines on receivable/payable accounts carry the intercompany partner with `amount_currency = 0` and would create zero mirror lines | Reading the exchange-difference code in `account_move_line.py` | Rule: lines with `amount_currency = 0` are skipped |
| The minimal UI (entry form, report pivot) was optional, although the task requires the auditor to open an entry | Re-reading the task requirements | Moved to mandatory |
| Translating intercompany balances at nominal was not marked as a deviation from IAS 21 | Accounting review of the assumptions | Recorded as an explicit simplification |
| The read-only auditor could not build the report, because the wizard writes report lines | Review of access rights | The wizard rebuilds report lines via `sudo()` |

When the oracle was switched to read the seed file, its output was compared with the first version: 94 journal lines, 36 elimination lines and every report figure matched.

## Not verified yet

Nothing has been run in a real Odoo instance. `docker-compose.yml` and `odoo.conf` follow the official image's entrypoint; plan step 0 verifies them.
