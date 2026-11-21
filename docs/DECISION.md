# Decision note: how, when and where eliminations are created

## Decision

**Where.** In the module's own tables: one *elimination entry* per month (`ELIM/2026/03`) with its lines. Never in `account.move`. The companies' books, and every standard Odoo report built on them, stay exactly as the companies booked them.

**How.** One rule, no pair matching. Every intercompany journal item gets a mirror line in USD at its nominal amount. Whatever a document leaves unbalanced (a payment, the loan) goes to *IC cash in transit*. Each side is removed in full on its own date, so:

- the Ukraine March invoice (31 March at Ukraine, 2 April at US) lowers group profit by 50,000 in March and raises it by 50,000 in April, and nets to zero;
- the US → Poland payment (31 March vs 1 April) shows as 10,000 cash in transit at 31 March and 0 at 30 April.

Every line links to its source journal item, and each entry has a counterparty reconciliation (seller vs buyer, per pair) that explains every difference.

**When.** At month close, with a button. *Generate* builds a draft from the current books. *Post* rebuilds it once more, locks it and freezes the reconciliation the auditor signs off. The group report uses posted entries as they are and computes the other months on the fly, so opening a report never changes anything.

## Options rejected

| Option | Why not |
| --- | --- |
| Elimination journal entries in Delta US's books | Delta US's standard P&L would no longer show its real books, which the task forbids. Delta US's books would also carry Ukraine's and Poland's accounts |
| A fourth "elimination company" with real journal entries | Needs its own chart of accounts, journals, rates and users. Community Odoo has no financial report that adds companies in different currencies together, so a custom report is needed anyway. Too much setup for a 2–3 hour task |
| Odoo Enterprise *Consolidation* app | Enterprise only. The task asks for a module that installs on the database we were given |
| Matching each seller document to the buyer's document | Breaks exactly on the task's traps: the invoice booked in another month and the payment in transit have no partner document on the same date. It would also need a shared reference on every document |
| Creating eliminations automatically on every posting | No stable "as of" figure for the auditor: a late document silently changes a month that was already reviewed |

## What this costs

- The elimination entry is not a standard journal entry, so it does not show in Odoo's general ledger. The auditor opens it under *Invoicing → Consolidation*, with a *Source* button on every line.
- A document backdated into a posted month is not picked up until someone resets that month's entry to draft and posts it again.
