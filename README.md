# Delta Group consolidation (Odoo 18)

Odoo module `delta_consolidation`: removes intercompany transactions and balances from Delta Group's USD reporting and leaves the three companies' books untouched.

- Eliminations are monthly **elimination entries** in the module's own tables — never in `account.move`, so each company's standard P&L always shows its real books.
- Every elimination line links to the source journal item; the auditor opens the entry, follows the links and sees a counterparty reconciliation.
- A **group report** per month: P&L and balance sheet for each company, the eliminations column and the group total in USD, as a pivot (Excel export is the pivot's standard button).

Why eliminations work this way, and which options were rejected: [`docs/DECISION.md`](docs/DECISION.md).

## Standard Odoo, and what the module adds

| Standard Odoo, used as it is | Added by the module |
| --- | --- |
| Multi-company in one database, each company with its own currency | A **group** that lists its member companies and its reporting currency (USD) |
| Invoices, vendor bills, credit notes and journal entries are the only source data | **Elimination entries**, monthly, kept in the module's own tables: draft → posted, locked once posted |
| Each company's own partner record, used to tell that a journal item is intercompany | An *Intercompany* flag on accounts, for the loan accounts |
| Currency rates and Odoo's own currency conversion | **Translation to USD** with a CTA line per company (one function, `_translate`) |
| Chart of accounts (`generic_coa`) and its account types to sort P&L and balance sheet | **Group report**: P&L and balance sheet per company, eliminations and group, as a pivot |
| Pivot view and its Excel export | **Counterparty reconciliation** on each entry, and a *Source* button on each line |
| Accounting user groups and multi-company record rules | Access rules: only users allowed in all three companies see the group; a read-only **auditor** |
| — | A **demo loader** that builds the three companies and their documents with one command |

The module never writes journal entries, so each company's standard reports show its real books.

## Run it from scratch (no programming needed)

You end up with Odoo running on your own computer at <http://localhost:8069>, with the module and the demo data already loaded. It takes about 15 minutes, most of it waiting. Nothing is installed on your computer except Docker, and everything can be removed afterwards (step 7).

### 1. Install Docker Desktop (once)

Docker runs Odoo and its database in isolated "containers", so you do not install Odoo, Python or PostgreSQL yourself.

- **Windows or Mac:** download Docker Desktop from <https://www.docker.com/products/docker-desktop/>, install it with the default options and start it. On Windows, accept if it asks to enable WSL 2, and restart the computer if it asks to. Wait until the Docker Desktop window says *Engine running* (a green status at the bottom left).
- **Linux:** install Docker Engine with the Compose plugin: <https://docs.docker.com/engine/install/>.

Docker Desktop must stay running while you use the project.

### 2. Get the project folder

- If you received a **ZIP file**, unzip it, for example to your desktop. You get a folder named `delta-consolidation` that contains this `README.md` and a file called `docker-compose.yml`.
- If you received a **Git link**, run `git clone <the link>` in a terminal instead.

### 3. Open a terminal in the project folder

- **Windows:** open the `delta-consolidation` folder in File Explorer, click the address bar, type `cmd` and press Enter.
- **Mac:** open the *Terminal* app, type `cd ` (with a space after it), drag the `delta-consolidation` folder into the Terminal window and press Enter.
- **Linux:** right-click inside the folder and choose *Open in Terminal*.

To check you are in the right place, type `docker compose version` and press Enter: it should print a version number. If it says the command is not found, Docker Desktop is not installed or not running (step 1).

### 4. Load the demo (one command, about 5–10 minutes the first time)

Copy this line into the terminal and press Enter:

```bash
docker compose run --rm demo
```

The first run downloads Odoo and PostgreSQL (about 1 GB to download; keep about 5 GB of free disk space), then creates the database, installs the module and loads the demo companies, invoices and elimination entries. A lot of text scrolls by; that is normal. It is finished when the terminal shows its prompt again and one of the last lines says `Delta demo data loaded`. Running the command again is safe: it says `already loaded` and changes nothing.

### 5. Start Odoo

```bash
docker compose up -d odoo
```

It returns after a few seconds with `Started`. Odoo keeps running in the background, even if you close the terminal.

### 6. Open it in your browser

1. Go to <http://localhost:8069>. If the page does not open yet, wait 20 seconds and reload.
2. Log in with email **admin** and password **admin**. (A second user, **auditor** / **auditor**, can look at everything but change nothing.)
3. Click your company name at the top right and tick all three companies: **Delta US Inc.**, **Delta Ukraine LLC** and **Delta Poland sp. z o.o.**
4. Click the grid icon at the top left and open **Invoicing**. In the top menu, open **Consolidation**:
   - **Elimination entries**: the monthly entries; open *ELIM/2026/03* first.
   - **Group report**: choose a month (for example *March*, year *2026*) and click **Open report**.

The table [What to look at](#what-to-look-at) below lists the figures you should see.

### 7. Stop, restart, remove

| To | Run in the project folder |
| --- | --- |
| Stop Odoo (data is kept) | `docker compose stop` |
| Start it again later | `docker compose up -d odoo` |
| Remove everything, including the database, to start over from step 4 | `docker compose down -v` |

### If something goes wrong

| What you see | What to do |
| --- | --- |
| `docker: command not found`, or *Cannot connect to the Docker daemon* | Start Docker Desktop and wait for *Engine running*, then repeat the command |
| *port is already allocated* / *address already in use* on step 5 | Another program uses port 8069 (often another Odoo). Close it, or run `docker compose down` in that other project, then repeat step 5 |
| The browser shows an Odoo *database manager* page instead of the login | Step 4 was skipped or did not finish: run `docker compose run --rm demo`, then reload the page |
| Login fails | Use **admin** as the email, not an email address; the database is `delta` |
| *Consolidation* is not in the menu | You are in another app (for example Discuss): open **Invoicing** from the grid icon |
| Anything else | Start clean: `docker compose down -v`, then steps 4–6 again |

### For developers

```bash
docker compose run --rm test
```

Runs the automated tests on a separate database `delta_test`; exit code 0 means all green (about 1 minute). `python docs/oracle.py --check` confirms that the committed expected figures match the demo data.

## Check the group results in five steps (for a controller)

Odoo is running with the demo data (steps 4–5 above). The auditor login is enough, and it cannot change anything.

1. **Log in and see all three companies.** Go to <http://localhost:8069> and log in as **auditor** / **auditor**. Click the company name at the top right and tick all three companies.
2. **Open the group report for March.** Click the grid icon at the top left, then **Invoicing → Consolidation → Group report**. Set *Month* to **March** and *Year* to **2026**, then click **Open report**. The columns are the three companies, *Eliminations* and *Total*. *Total* is the group.
3. **Check that intercompany is gone.** In the *Total* column, every row marked **(IC)** is **0.00**. Group profit (*Profit and loss* row) is **86,000**: external revenue 200,000 minus costs 114,000. Group assets are **794,166.67**.
4. **Open the elimination entry the auditor signs.** **Consolidation → Elimination entries → ELIM/2026/03**. Debit total = credit total = **94,000**, effect on profit **−50,000**, cash in transit **10,000**. The *Counterparty reconciliation* tab explains both differences: Ukraine's 50,000 March invoice that Delta US booked in April, and Delta US's 10,000 payment that Delta Poland received on 1 April.
5. **Trace a line back to the books.** On any line of the entry, click **Source**: the company's original invoice or entry opens. Then open **Accounting → Journal Entries**: there are no ELIM entries there, so each company's books are unchanged.

To download the report, use the download button above the pivot (Excel). The table below lists more figures to compare.

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
4. **Lifecycle**: *Generate* rebuilds a draft; *Post* regenerates it from the current books, locks it and freezes its counterparty reconciliation. The report uses posted entries as they are and computes the other months on the fly, so building it changes nothing.
5. **Access**: only users allowed in all three companies see the group, its entries and its report; each user gets their own report rows.

## Demo data

One file, [`delta_consolidation/data/demo_dataset.json`](delta_consolidation/data/demo_dataset.json), read by the loader and by the independent oracle. It covers everything the task asks for: monthly Ukraine → US and Poland → US invoices for January–March, the Ukraine March invoice of USD 50,000 dated 31 March but booked by Delta US on 2 April, a partial credit note on a Poland → US invoice, the 31 March payment Delta Poland records on 1 April, the USD 200,000 loan of 15 January, and external sales and costs for all three companies.

## How the numbers are proven

- [`docs/oracle.py`](docs/oracle.py) is a plain-Python calculation of the same rules, without Odoo. It wrote [`expected_figures.json`](delta_consolidation/tests/expected_figures.json) **before** the module existed; the tests only compare with it and contain no numbers.
- 28 tests (`delta_consolidation/tests/`): company books in local currency, cut-off dates, books unchanged by eliminations, every entry's line count and totals, cut-off effect, credit note, cash in transit, loan, group P&L for each month, group balance sheet at each month end (row by row, per entity), counterparty reconciliation, idempotency and locking, the non-USD exception list, auditor rights, the source links, and regressions for the independent review's findings (section lines, company isolation, exchange differences after reconciliation, prior-year activity, post after late documents).
- The tests fail when the figures are wrong: changing one number in `expected_figures.json` makes `docker compose run --rm test` exit 1.

| Group figures, USD | January | February | March | April |
| --- | --- | --- | --- | --- |
| Profit | 66,000 | 76,000 | 86,000 | 0 |
| Effect of eliminations on profit | 0 | 0 | −50,000 | +50,000 |
| Cash in transit at month end | 0 | 0 | 10,000 | 0 |

## Assumptions

See [`ASSUMPTIONS.md`](ASSUMPTIONS.md): 20 assumptions made before implementation (Odoo 18 Community, separate root companies, one `generic_coa` chart, USD intercompany documents without taxes, current-rate translation with CTA, no revaluation of intercompany balances, monthly button-driven entries, …) and the decisions taken when Odoo behaved differently from the plan.

## Not done, and why

| Not done | Why / what it would take |
| --- | --- |
| Elimination of investment in subsidiaries, equity, minority interest, unrealised profit | Not in the demo; the task's flows are services, invoices and a loan |
| IAS 21 revaluation of intercompany USD balances in the subsidiaries | Simplification (assumption 8): the difference goes to CTA instead of P&L |
| Opening balances and multi-year runs | Prior-year P&L is shown as retained earnings and prior-year intercompany items are eliminated, but year-end closing and opening balances are not modelled (assumption 11) |
| Intercompany documents in other currencies | Detected and listed on the entry as exceptions, not eliminated |
| Intercompany documents addressed to a contact of a group company | Detection matches the company's own partner exactly |
| Account mapping between different charts of accounts | All companies use `generic_coa` (assumption 3) |
| A "stale entry" flag when a document is backdated into a posted month | Reset that month's entry to draft and generate it again |
| Average-rate translation of the P&L | Rate on the line date (assumption 7) |
| Polished QWeb/PDF report | The pivot covers the requirement; time went to the tests on the numbers |

## Repository

| Path | Contents |
| --- | --- |
| `delta_consolidation/` | The module: `models/` (group, elimination entry, report, demo loader), `wizard/`, `views/`, `security/`, `data/`, `tests/`, `scripts/load_demo.py` |
| `docs/DECISION.md` | Decision note: how, when and where eliminations are created; options rejected |
| `docs/SPEC.md` | Rules and models |
| `docs/PLAN.md`, `docs/PLANNING_LOG.md` | The plan written before implementation, and how it was made |
| `docs/AI_WORKFLOW.md` | How AI was used, and how its output was checked |
| `docs/oracle.py` | Independent calculation of the expected figures |
| `docker-compose.yml`, `odoo.conf` | The environment |
