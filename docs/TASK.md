# Task

Transcribed from `docs/TASK.png`. The screenshot ends after item 4 of "What to build"; check the original handout for anything that follows.

There is no live-coding test. We want to see how you actually work: how you understand a business problem, which assumptions you make, how you build with your normal tools (with focus on your AI setup), and how you know the result is right.

> **Spend two to three hours. You might not be able to do everything, and that is deliberate.** Decide what matters, make your assumptions, and write them down.

## The situation

Delta Group has three companies. Each keeps its own books in its own currency. All three work in one Odoo database.

| Company | Currency | What it does |
| --- | --- | --- |
| Delta US Inc. | USD | The parent company. It sells to clients in the US, and the group reports in USD. Payroll in USD. |
| Delta Ukraine LLC | UAH | Delivers engineering for Delta US client projects, and invoices Delta US monthly in USD. Payroll in UAH. Delta US also lent it USD 200,000 on 15 January. |
| Delta Poland sp. z o.o. | PLN | Sells to its own clients in Poland. It also delivers design work for Delta US, and invoices Delta US monthly in USD. Payroll in PLN. |

So there are two intercompany directions: **Ukraine → US** and **Poland → US**.

**What Finance wants:** standalone books for each company, in its own currency, **and** the group's results in USD, as if the group were one company. The group figures show what it earned from outside clients, and what it owns and owes to the outside world. Two further requirements:

- the standard Profit and Loss must always show a company's real books;
- the auditor wants an elimination entry they can open.

## What to build

An Odoo module that you can hand over, and that we can install and run.

1. **Eliminations. This is the core of the task.** The module removes transactions and balances between group companies from the group view. You decide how and when eliminations are created.
2. **Standalone and group results.** A consolidated profit and loss and balance sheet for a chosen month, alongside each company's own results. A report, a pivot view or an export are all fine.
3. **Demo data.** You have no access to real data, so create data that proves the module works. Someone else must be able to load it with one command. It must include at least:
   - Delta Ukraine's and Delta Poland's monthly invoices to Delta US, January to March. **Ukraine's March invoice of USD 50,000 is dated 31 March by Delta Ukraine, and booked by Delta US on 2 April;**
   - a partial credit note on one Poland → US invoice;
   - a payment Delta US makes to Delta Poland on 31 March, which Delta Poland records on 1 April;
   - external sales and costs for each of the three companies.
4. **Automated tests** that prove the numbers, not just the screens.
