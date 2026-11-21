# Assumptions

These assumptions close what the task leaves open. Decisions taken during implementation are added at the end.

| # | Assumption | Why, and what stays out of scope |
| --- | --- | --- |
| 1 | Odoo 18.0 Community in Docker; the module depends on `account` only | The task names no version. Moving to 19.0 or 20.0 means changing the image tag and running the tests. The module installs the same way on Enterprise |
| 2 | The three companies are separate root companies, not branches | A branch (`parent_id`) always inherits its parent's currency |
| 3 | One chart of accounts, `generic_coa`, for all three; no country is set on the companies | Local charts (`l10n_ua`, `l10n_pl`) and an account mapping table are out of scope |
| 4 | Intercompany documents are always in USD | The task says so. A line in another currency goes to the exception list instead of being silently lost |
| 5 | Intercompany invoices carry no taxes | VAT on cross-border services is out of scope |
| 6 | An intercompany line = a journal item whose partner is another group company, on a receivable/payable, income or expense account, or on an account flagged Intercompany | Detection by partner, not by account number |
| 7 | Translation to USD: P&L at the rate on the line date; assets and liabilities at the month-end rate; equity at the historical rate; the difference goes to a separate CTA line in equity | The standard current-rate method. No monthly average rate |
| 8 | Subsidiaries do not revalue foreign-currency balances; intercompany USD balances are taken at nominal | A simplification versus IAS 21: under the standard, the FX difference on the loan and intercompany balances would hit the subsidiary's and the group's P&L; here it goes to CTA |
| 9 | Exchange differences are not eliminated | They are a real result of the group |
| 10 | Eliminated: transactions and balances — invoices, credit notes, payments, the loan | Investment in subsidiaries' equity, minority interest and unrealised profit are out of scope |
| 11 | One calendar fiscal year, no opening balances | Carrying elimination effects across the year end is out of scope |
| 12 | No interest is accrued on the loan | If accrued, it falls under the general income/expense elimination rule |
| 13 | Eliminations are created with a button at month close; a draft is regenerated, a posted entry is locked | Auto-creation on every posting gives no verifiable result as of a date |
| 14 | Delta Ukraine has a small external sale in the demo | Its description says it works only for Delta US, but the demo requires external sales for all three companies |
| 15 | Rates: one shared table without a company, USD base; the values are illustrative | 40 / 41 / 42 / 43 UAH and 4.0 / 4.1 / 4.2 / 4.3 PLN per USD from the 1st of January–April 2026 |

## Decisions taken during implementation

Recorded when Odoo behaved differently from the plan or the plan left a detail open.

| Date | Decision | Reason |
| --- | --- | --- |
