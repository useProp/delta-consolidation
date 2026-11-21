#!/usr/bin/env python3
"""Independent oracle for the Delta Group consolidation (plain Python, no Odoo).

Reads the demo seed file, applies the elimination and translation rules from
docs/SPEC.md and writes the expected figures that the module's tests compare to.

    python docs/oracle.py           print the figures and write expected_figures.json
    python docs/oracle.py --check   exit 1 if expected_figures.json is missing or out of date

Seeds:    delta_consolidation/data/demo_dataset.json
Expected: delta_consolidation/tests/expected_figures.json  (generated, never edit by hand)
"""
import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / 'delta_consolidation' / 'data' / 'demo_dataset.json'
EXPECTED = ROOT / 'delta_consolidation' / 'tests' / 'expected_figures.json'

TRANSIT = 'IC cash in transit'
CYE = 'Current year earnings'
CTA = 'CTA'
PL_SECTIONS = ('income', 'expense')
INVOICE_SIGN = {'out_invoice': 1, 'out_refund': -1, 'in_invoice': -1, 'in_refund': 1}
ROW_ORDER = [
    ('Bank', False), (TRANSIT, False), ('Receivable', False), ('Receivable', True),
    ('IC loan receivable', True), ('Payable', False), ('Bank loan', False), ('Payable', True),
    ('IC loan payable', True), ('Capital', False), (CYE, False), (CTA, False),
]


def to_date(value):
    return date.fromisoformat(value)


def month_bounds(month):
    year, mon = map(int, month.split('-'))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1) - timedelta(days=1)
    return start, end


def section_of(account_type):
    for prefix in ('income', 'expense', 'equity', 'asset', 'liability'):
        if account_type.startswith(prefix):
            return prefix
    raise ValueError(f'unknown account type {account_type}')


def r2(value):
    value = round(value + 0.0, 2)
    return 0.0 if value == 0 else value


class Oracle:
    def __init__(self, raw):
        self.raw = raw
        self.companies = list(raw['companies'])
        self.entities = self.companies + ['ELIM']
        self.ccy = {key: c['currency'] for key, c in raw['companies'].items()}
        self.gcur = raw['group']['currency']
        self.rates = {cur: sorted((to_date(k), v) for k, v in table.items())
                      for cur, table in raw['rates_per_usd'].items()}
        self.accounts = raw['accounts']
        self.lines = self._build_lines()
        self.elim, self.exceptions = self._eliminate()

    # ---------------------------------------------------------------- rates
    def rate(self, cur, day):
        """Units of `cur` per 1 USD valid on `day` (latest rate on or before the day)."""
        if cur == 'USD':
            return 1.0
        found = None
        for start, value in self.rates[cur]:
            if start <= day:
                found = value
        if found is None:
            raise ValueError(f'no {cur} rate on {day}')
        return found

    def convert(self, amount, from_cur, to_cur, day):
        return amount * self.rate(to_cur, day) / self.rate(from_cur, day)

    # ---------------------------------------------------------------- books
    def _line(self, doc, day, account, balance, cur, amount_currency, partner):
        acc = self.accounts[account]
        section = section_of(acc['account_type'])
        company = doc['company']
        group_partner = partner if partner in self.companies and partner != company else None
        is_ic = bool(group_partner) and (
            acc['account_type'] in ('asset_receivable', 'liability_payable')
            or acc.get('is_intercompany', False)
            or section in PL_SECTIONS
        )
        return {
            'doc': doc['id'], 'co': company, 'date': day, 'account': account,
            'label': acc['label'], 'section': section, 'bal': balance,
            'cur': cur, 'amt': amount_currency, 'ic': group_partner if is_ic else None,
        }

    def _build_lines(self):
        lines, seen = [], set()
        for doc in self.raw['documents']:
            if doc['id'] in seen:
                raise ValueError(f"duplicate document id {doc['id']}")
            seen.add(doc['id'])
            company_cur = self.ccy[doc['company']]
            doc_lines = []
            if doc['type'] == 'entry':
                day = to_date(doc['date'])
                for vals in doc['lines']:
                    cur = vals.get('currency', company_cur)
                    amt = vals['amount_currency'] if cur != company_cur else vals['balance']
                    if cur != company_cur:
                        expected = round(self.convert(amt, cur, company_cur, day), 2)
                        if abs(expected - vals['balance']) > 0.005:
                            raise ValueError(f"{doc['id']}: balance {vals['balance']} != {expected} at the {day} rate")
                    doc_lines.append(self._line(doc, day, vals['account'], vals['balance'], cur, amt, vals.get('partner')))
            else:
                rate_day = to_date(doc['invoice_date'])            # Odoo takes the invoice rate from invoice_date
                day = to_date(doc.get('date', doc['invoice_date']))  # accounting date
                cur, sign = doc['currency'], INVOICE_SIGN[doc['type']]
                counterpart = 'receivable' if doc['type'].startswith('out') else 'payable'
                total_amt = total_bal = 0.0
                for vals in doc['lines']:
                    amt = -sign * vals['amount']
                    bal = round(self.convert(amt, cur, company_cur, rate_day), 2)
                    doc_lines.append(self._line(doc, day, vals['account'], bal, cur, amt, doc['partner']))
                    total_amt += amt
                    total_bal += bal
                doc_lines.append(self._line(doc, day, counterpart, -total_bal, cur, -total_amt, doc['partner']))
            if abs(sum(l['bal'] for l in doc_lines)) > 0.005:
                raise ValueError(f"{doc['id']} is not balanced")
            lines += doc_lines
        return lines

    # ---------------------------------------------------------- eliminations
    def _eliminate(self):
        by_doc, exceptions = defaultdict(list), []
        for line in self.lines:
            if not line['ic']:
                continue
            if line['cur'] != self.gcur:
                exceptions.append(line['doc'])
                continue
            if abs(line['amt']) < 0.005:          # exchange-difference lines carry no nominal
                continue
            by_doc[line['doc']].append(line)
        elim = []
        for doc_id, lines in by_doc.items():
            total = 0.0
            for line in lines:
                elim.append({'date': line['date'], 'co': line['co'], 'counterparty': line['ic'],
                             'label': line['label'], 'section': line['section'],
                             'usd': -line['amt'], 'kind': 'mirror', 'source': doc_id})
                total += line['amt']
            if abs(total) > 0.005:
                first = lines[0]
                elim.append({'date': first['date'], 'co': first['co'], 'counterparty': first['ic'],
                             'label': TRANSIT, 'section': 'asset',
                             'usd': total, 'kind': 'transit', 'source': doc_id})
        return elim, sorted(set(exceptions))

    # ----------------------------------------------------------- translation
    def translate(self, line, closing):
        company_cur = self.ccy[line['co']]
        if company_cur == self.gcur:
            return line['bal']
        if line['ic'] and line['cur'] == self.gcur:
            return line['amt']
        if line['section'] in PL_SECTIONS + ('equity',):
            return self.convert(line['bal'], company_cur, self.gcur, line['date'])
        return self.convert(line['bal'], company_cur, self.gcur, closing)

    # --------------------------------------------------------------- reports
    def pl_detail(self, start, end):
        """{(entity, label, is_ic): profit contribution in USD} for lines dated start..end."""
        usd, local = defaultdict(float), defaultdict(float)
        for line in self.lines:
            if line['section'] in PL_SECTIONS and start <= line['date'] <= end:
                key = (line['co'], line['label'], bool(line['ic']))
                usd[key] -= self.translate(line, end)
                local[key] -= line['bal']
        for e in self.elim:
            if e['section'] in PL_SECTIONS and start <= e['date'] <= end:
                usd[('ELIM', e['label'], True)] -= e['usd']
        return usd, local

    def bs_detail(self, closing):
        """{(entity, label, is_ic): debit minus credit in USD} as of `closing`."""
        usd, local, totals = defaultdict(float), defaultdict(float), defaultdict(float)
        for line in self.lines:
            if line['date'] > closing:
                continue
            value = self.translate(line, closing)
            totals[line['co']] += value
            key = (line['co'], CYE, False) if line['section'] in PL_SECTIONS else (line['co'], line['label'], bool(line['ic']))
            usd[key] += value
            local[key] += line['bal']
        for co in self.companies:
            if abs(totals[co]) > 0.000001:
                usd[(co, CTA, False)] = -totals[co]
        for e in self.elim:
            if e['date'] > closing:
                continue
            if e['section'] in PL_SECTIONS:
                usd[('ELIM', CYE, False)] += e['usd']
            else:
                usd[('ELIM', e['label'], e['kind'] == 'mirror')] += e['usd']
        return usd, local

    def section_of_label(self, label):
        if label in (CYE, CTA):
            return 'equity'
        if label == TRANSIT:
            return 'asset'
        for acc in self.accounts.values():
            if acc['label'] == label:
                return section_of(acc['account_type'])
        raise ValueError(label)

    def figures(self):
        months = self.raw['report_months']
        year_start = date(int(months[0][:4]), 1, 1)
        out = {
            'generated_by': 'docs/oracle.py',
            'dataset_sha256': hashlib.sha256(DATASET.read_bytes()).hexdigest(),
            'group_currency': self.gcur,
            'profit_usd': {}, 'profit_local': {}, 'external_revenue_usd': {},
            'group_profit_ytd_usd': {}, 'eliminations': {}, 'balance_sheet_usd': {},
            'balance_local': {}, 'transit_usd': {}, 'ic_reconciliation_usd': {},
            'exceptions': self.exceptions,
        }
        for month in months:
            start, end = month_bounds(month)
            usd, local = self.pl_detail(start, end)
            profit = {e: r2(sum(v for k, v in usd.items() if k[0] == e)) for e in self.entities}
            profit['GROUP'] = r2(sum(usd.values()))
            out['profit_usd'][month] = profit
            out['profit_local'][month] = {c: r2(sum(v for k, v in local.items() if k[0] == c)) for c in self.companies}
            out['external_revenue_usd'][month] = r2(sum(v for k, v in usd.items()
                                                        if k[1] == 'Revenue' and not k[2] and k[0] != 'ELIM'))
            ytd_usd, _ = self.pl_detail(year_start, end)
            out['group_profit_ytd_usd'][month] = r2(sum(ytd_usd.values()))
            month_elim = [e for e in self.elim if start <= e['date'] <= end]
            out['eliminations'][month] = {
                'lines': len(month_elim),
                'debit': r2(sum(e['usd'] for e in month_elim if e['usd'] > 0)),
                'credit': r2(-sum(e['usd'] for e in month_elim if e['usd'] < 0)),
                'pl_effect': r2(-sum(e['usd'] for e in month_elim if e['section'] in PL_SECTIONS)),
            }
            if abs(sum(e['usd'] for e in month_elim)) > 0.005:
                raise AssertionError(f'elimination entry {month} is not balanced')
            closing = end.isoformat()
            out['balance_sheet_usd'][closing] = self._bs_figures(end)
            out['balance_local'][closing] = self._bs_local(end)
            out['transit_usd'][closing] = r2(self.bs_detail(end)[0].get(('ELIM', TRANSIT, False), 0.0))
            out['ic_reconciliation_usd'][closing] = self._ic_reconciliation(end)
        return out

    def _bs_figures(self, closing):
        usd, _ = self.bs_detail(closing)
        keys = {(k[1], k[2]) for k in usd}
        ordered = [k for k in ROW_ORDER if k in keys] + sorted(keys - set(ROW_ORDER))
        rows, totals = [], {'assets': defaultdict(float), 'liabilities_equity': defaultdict(float)}
        for label, is_ic in ordered:
            section = self.section_of_label(label)
            sign = 1 if section == 'asset' else -1
            row = {'label': label, 'intercompany': is_ic, 'section': section}
            for ent in self.entities:
                row[ent] = r2(sign * usd.get((ent, label, is_ic), 0.0))
            row['GROUP'] = r2(sign * sum(usd.get((ent, label, is_ic), 0.0) for ent in self.entities))
            if any(row[ent] for ent in self.entities):
                rows.append(row)
            bucket = 'assets' if section == 'asset' else 'liabilities_equity'
            for ent in self.entities:
                totals[bucket][ent] += sign * usd.get((ent, label, is_ic), 0.0)
        for ent in self.entities:
            if abs(totals['assets'][ent] - totals['liabilities_equity'][ent]) > 0.005:
                raise AssertionError(f'balance sheet of {ent} does not balance on {closing}')
        for row in rows:
            if row['intercompany'] and abs(row['GROUP']) > 0.005:
                raise AssertionError(f"intercompany row {row['label']} is not eliminated on {closing}")
        result = {}
        for bucket, values in totals.items():
            values['GROUP'] = sum(values[ent] for ent in self.entities)
            result[bucket] = {k: r2(v) for k, v in values.items()}
        return {'rows': rows, 'totals': result}

    def _bs_local(self, closing):
        _, local = self.bs_detail(closing)
        result = {}
        for co in self.companies:
            values = {}
            for (ent, label, is_ic), value in local.items():
                if ent != co:
                    continue
                sign = 1 if self.section_of_label(label) == 'asset' else -1
                values[label + (' (IC)' if is_ic else '')] = r2(sign * value)
            result[co] = {k: v for k, v in sorted(values.items()) if v}
        return result

    def _ic_reconciliation(self, closing):
        pairs = sorted({(l['co'], l['ic']) for l in self.lines
                        if l['ic'] and l['section'] == 'income' and l['date'] <= closing})
        result = []
        for seller, buyer in pairs:
            def total(co, partner, sections):
                return sum(l['amt'] for l in self.lines
                           if l['co'] == co and l['ic'] == partner and l['date'] <= closing
                           and self.accounts[l['account']]['account_type'] in sections)
            result.append({
                'pair': f'{seller}->{buyer}',
                'seller_receivable': r2(total(seller, buyer, ('asset_receivable',))),
                'buyer_payable': r2(-total(buyer, seller, ('liability_payable',))),
                'seller_revenue': r2(-total(seller, buyer, ('income',))),
                'buyer_expense': r2(sum(l['amt'] for l in self.lines
                                        if l['co'] == buyer and l['ic'] == seller and l['date'] <= closing
                                        and l['section'] == 'expense')),
            })
        return result


def render(fig):
    out = []
    w = out.append
    w('Profit by month, USD')
    for month, values in fig['profit_usd'].items():
        w(f"  {month}  " + '  '.join(f'{k} {v:>12,.2f}' for k, v in values.items())
          + f"   external revenue {fig['external_revenue_usd'][month]:,.2f}"
          + f"   group YTD {fig['group_profit_ytd_usd'][month]:,.2f}")
    w('Profit by month, company currency')
    for month, values in fig['profit_local'].items():
        w(f"  {month}  " + '  '.join(f'{k} {v:>14,.2f}' for k, v in values.items()))
    w('Elimination entries')
    for month, e in fig['eliminations'].items():
        w(f"  ELIM/{month.replace('-', '/')}  lines {e['lines']:>2}  debit = credit {e['debit']:>12,.2f}  P&L effect {e['pl_effect']:>12,.2f}")
    for closing, bs in fig['balance_sheet_usd'].items():
        w(f'Balance sheet {closing}, USD   (transit {fig["transit_usd"][closing]:,.2f})')
        head = ['US', 'UA', 'PL', 'ELIM', 'GROUP']
        w('  ' + 'row'.ljust(26) + ''.join(h.rjust(15) for h in head))
        for row in bs['rows']:
            name = row['label'] + (' (IC)' if row['intercompany'] else '')
            w('  ' + name.ljust(26) + ''.join(f'{row[h]:>15,.2f}' for h in head))
        for bucket, values in bs['totals'].items():
            w('  ' + ('= ' + bucket).ljust(26) + ''.join(f'{values[h]:>15,.2f}' for h in head))
    w('IC reconciliation, USD nominal')
    for closing, pairs in fig['ic_reconciliation_usd'].items():
        for p in pairs:
            w(f"  {closing} {p['pair']}: receivable {p['seller_receivable']:,.0f} vs payable {p['buyer_payable']:,.0f}"
              f" | revenue {p['seller_revenue']:,.0f} vs expense {p['buyer_expense']:,.0f}")
    w(f"Exceptions (IC lines not in {fig['group_currency']}): {fig['exceptions'] or 'none'}")
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='fail if expected_figures.json is out of date')
    args = parser.parse_args()
    fig = Oracle(json.loads(DATASET.read_text(encoding='utf-8'))).figures()
    text = json.dumps(fig, indent=2, ensure_ascii=False) + '\n'
    if args.check:
        current = EXPECTED.read_text(encoding='utf-8') if EXPECTED.exists() else ''
        if current != text:
            print(f'{EXPECTED.relative_to(ROOT)} is out of date: run python docs/oracle.py', file=sys.stderr)
            return 1
        print('expected_figures.json is up to date')
        return 0
    print(render(fig))
    EXPECTED.parent.mkdir(parents=True, exist_ok=True)
    EXPECTED.write_text(text, encoding='utf-8')
    print(f'\nwritten {EXPECTED.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
