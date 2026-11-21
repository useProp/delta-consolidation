# Delta Group consolidation (Odoo 18)

Odoo module `delta_consolidation`: removes intercompany transactions and balances from Delta Group's USD reporting and leaves the three companies' books untouched.

- Eliminations are monthly **elimination entries** in the module's own tables — never in `account.move`, so each company's standard P&L always shows its real books.
- Every elimination line links to the source journal item; the auditor opens the entry, follows the links and sees a counterparty reconciliation.
- A **group report** per month: P&L and balance sheet for each company, the eliminations column and the group total in USD, as a pivot (Excel export is the pivot's standard button).

## Run it

Needs Docker with Compose. The first run downloads the images (5–10 min); each new database takes 1–3 min.

```bash
docker compose run --rm demo
```

```bash
docker compose run --rm test
```

```bash
docker compose up -d odoo
```

1. `demo` creates the database `delta`, installs the module and loads the demo data. Running it again changes nothing.
2. `test` runs the automated tests on a separate database `delta_test`; exit code 0 = all green.
3. `odoo` serves the UI at <http://localhost:8069>, database `delta`: **admin / admin**, or **auditor / auditor** for the read-only role (local passwords only).

In the UI: *Invoicing/Accounting → Consolidation → Elimination entries / Group report*. To open the source documents of all three companies, tick the three Delta companies in the company switcher.

Reset everything: `docker compose down -v`. Check that the committed expected figures match the seeds: `python docs/oracle.py --check`.

## What to look at

| Where | What you should see |
| --- | --- |
| Elimination entries | ELIM/2026/01–03 posted, ELIM/2026/04 draft |
| ELIM/2026/03 | 12 lines, debit = credit = 94,000; effect on profit −50,000; cash in transit 10,000; each line's *Source* button opens the company's document; tab *Counterparty reconciliation*: Ukraine → US 50,000 difference (March invoice not yet booked by US), Poland → US 10,000 (payment in transit) |
| Group report, March 2026 | P&L total of the group column 86,000; external revenue (*Income*, rows without "(IC)") 200,000; balance sheet assets 794,166.67; every "(IC)" row is 0 in the total column; CTA −8,166.67 |
| Group report, April 2026 | Cash in transit 0; group year-to-date earnings still 228,000 |
| Delta Ukraine → journal items | No module entries; March income minus expenses UAH 1,176,000 |

## How it works

Full rules: [`docs/SPEC.md`](docs/SPEC.md). In short:

1. **Intercompany line** = a posted journal item whose partner is another group company, on a receivable/payable account, an account flagged *Intercompany* (the loan accounts), or an income/expense account (exchange-difference journal excluded).
2. **Elimination entry** of a month: each intercompany line gets a mirror line `−amount_currency` in USD at nominal; whatever a document leaves unbalanced (a payment, the loan) goes to *IC cash in transit*. The two sides are never matched, so each is removed on its own date — the cut-off and cash-in-transit traps resolve themselves and cancel in the following month.
3. **Translation to USD**: USD books as they are; intercompany USD lines at nominal; P&L and equity at the rate on the line date; other balances at the month-end rate; the difference is the company's CTA line in equity.
4. **Lifecycle**: *Generate* rebuilds a draft, *Post* locks it. Building the report generates missing or draft entries from January up to the month and leaves posted ones alone.

## Demo data

One file, [`delta_consolidation/data/demo_dataset.json`](delta_consolidation/data/demo_dataset.json), read by the loader and by the independent oracle. It covers everything the task asks for: monthly Ukraine → US and Poland → US invoices for January–March, the Ukraine March invoice of USD 50,000 dated 31 March but booked by Delta US on 2 April, a partial credit note on a Poland → US invoice, the 31 March payment Delta Poland records on 1 April, the USD 200,000 loan of 15 January, and external sales and costs for all three companies.

## How the numbers are proven

- [`docs/oracle.py`](docs/oracle.py) is a plain-Python calculation of the same rules, without Odoo. It wrote [`expected_figures.json`](delta_consolidation/tests/expected_figures.json) **before** the module existed; the tests only compare with it and contain no numbers.
- 21 tests (`delta_consolidation/tests/`): company books in local currency, cut-off dates, books unchanged by eliminations, every entry's line count and totals, cut-off effect, credit note, cash in transit, loan, group P&L for each month, group balance sheet at each month end (row by row, per entity), counterparty reconciliation, idempotency and locking, the non-USD exception list, auditor rights, and the source links.
- The tests fail when the figures are wrong: changing one number in `expected_figures.json` makes `docker compose run --rm test` exit 1.

| Group figures, USD | January | February | March | April |
| --- | --- | --- | --- | --- |
| Profit | 66,000 | 76,000 | 86,000 | 0 |
| Effect of eliminations on profit | 0 | 0 | −50,000 | +50,000 |
| Cash in transit at month end | 0 | 0 | 10,000 | 0 |

## Assumptions

See [`ASSUMPTIONS.md`](ASSUMPTIONS.md): 15 assumptions made before implementation (Odoo 18 Community, separate root companies, one `generic_coa` chart, USD intercompany documents without taxes, current-rate translation with CTA, no revaluation of intercompany balances, monthly button-driven entries, …) and the decisions taken when Odoo behaved differently from the plan.

## Not done, and why

| Not done | Why / what it would take |
| --- | --- |
| Elimination of investment in subsidiaries, equity, minority interest, unrealised profit | Not in the demo; the task's flows are services, invoices and a loan |
| IAS 21 revaluation of intercompany USD balances in the subsidiaries | Simplification (assumption 8): the difference goes to CTA instead of P&L |
| Opening balances and multi-year runs | One calendar year, no carry-forward of elimination effects (assumption 11) |
| Intercompany documents in other currencies | Detected and listed on the entry as exceptions, not eliminated |
| Account mapping between different charts of accounts | All companies use `generic_coa` (assumption 3) |
| A "stale entry" flag when a document is backdated into a posted month | Reset that month's entry to draft and generate it again |
| Average-rate translation of the P&L | Rate on the line date (assumption 7) |
| Polished QWeb/PDF report | The pivot covers the requirement; time went to the tests on the numbers |

## Repository

| Path | Contents |
| --- | --- |
| `delta_consolidation/` | The module: `models/` (group, elimination entry, report, demo loader), `wizard/`, `views/`, `security/`, `data/`, `tests/`, `scripts/load_demo.py` |
| `docs/SPEC.md` | Rules and models |
| `docs/PLAN.md`, `docs/PLANNING_LOG.md` | The plan written before implementation, and how it was made |
| `docs/AI_WORKFLOW.md` | How AI was used, and how its output was checked |
| `docs/oracle.py` | Independent calculation of the expected figures |
| `docker-compose.yml`, `odoo.conf` | The environment |
