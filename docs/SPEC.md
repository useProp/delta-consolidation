# Specification: `delta_consolidation`

The rules the module implements and `docs/oracle.py` reproduces independently. Background and rationale: `docs/PLAN.md`, assumptions: `ASSUMPTIONS.md`.

## Principle

Eliminations live in the module's own models and never reach `account.move`. The companies' standard reports read only the company books, so eliminations never appear in them. The group report = translated journal items of the group companies + elimination lines as a separate column.

## Models

| Model | Purpose | Key fields |
| --- | --- | --- |
| `delta.consol.group` | Group members and reporting currency | `company_ids`, `currency_id` |
| `delta.consol.elimination` | Elimination entry for one group and month — the auditor's document | `name` (ELIM/2026/03), `date_from`, `date_to`, `state` (draft / posted), `line_ids`, totals, exception list |
| `delta.consol.elimination.line` | Elimination line | `kind` (mirror / transit), `source_line_id` → `account.move.line` (`ondelete='restrict'`), `company_id`, `counterparty_company_id`, `account_id`, `date`, `balance` in USD |
| `delta.consol.report.line` | Report line for the chosen month, regenerated | `statement` (pl / bs), `section`, `account_label`, `entity`, `is_intercompany`, `amount_local` (no aggregator), `amount_usd`, `balance_usd` |
| `delta.consol.report.wizard` | Picks a month, rebuilds report lines (via `sudo()`), opens the pivot | `group_id`, `month` |
| `delta.consol.demo` | Demo loader (AbstractModel), shared by `scripts/load_demo.py` and the tests | `load()` |
| `account.account` (extension) | Flags intercompany loan accounts | `is_intercompany` |

Engine functions (no UI, called directly by the tests):

1. `_ic_lines(group, date_from, date_to)` — intercompany journal items.
2. `_translate(line, closing_date)` — a journal item in USD. The only currency conversion in the module.
3. `_report_rows(group, month)` — report rows: the companies' books plus the eliminations column.

## Intercompany line

All of:

- `parent_state = 'posted'`;
- `partner_id` is the partner of another group company;
- balance-sheet account of type `asset_receivable` / `liability_payable` or with `is_intercompany = True`, **or** a P&L account (`income*` / `expense*`) outside the company's exchange-difference journal.

Then:

- `amount_currency = 0` → skipped (exchange-difference lines carry no nominal);
- line currency is not USD → not mirrored, listed as an exception on the entry.

## Monthly elimination entry

1. IC lines dated within the month.
2. One mirror line per IC line: same account, company and date, `balance = −amount_currency`, `source_line_id` set.
3. Per source `move_id`: `S` = sum of `amount_currency` over its IC lines; if `S ≠ 0`, a `transit` line of `+S` ("IC cash in transit", an asset).
4. Invariant: the entry's balances sum to 0.

Lifecycle: Generate rebuilds a draft; Post locks it; Reset to draft unlocks. A posted entry is never regenerated. The report generates missing entries from the start of the year up to the report month and leaves posted entries alone.

## Translation to USD (first matching rule)

1. Company currency is USD → `balance`.
2. IC line in USD → `amount_currency`.
3. P&L line → `balance` at the rate on the line date.
4. Equity → `balance` at the rate on the line date.
5. Other assets and liabilities → `balance` at the report month-end rate.

Rates: `company_currency._convert(amount, usd, company, date, round=False)`; round only on output.

## Report

- P&L: lines dated within the month; `amount_usd` = profit contribution (income positive, expense negative).
- Balance sheet at month end, cumulative from the start of the year: one row per account label; P&L accounts collapse into "Current year earnings"; per company a CTA row = minus the sum of all its translated lines; eliminations column = elimination lines up to the month end (P&L lines into "Current year earnings").
- `balance_usd` = debit minus credit; the balance-sheet total per entity and for the group is 0.
- Pivot: rows statement / section / account, columns entity; the total column is the group.

## Counterparty reconciliation

Per seller → buyer pair, cumulative at the entry's month end, USD nominal: seller receivable vs buyer payable, seller revenue vs buyer expense, and the differences.
