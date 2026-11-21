from collections import defaultdict

from odoo.tests import tagged

from .common import PL_PREFIXES, DeltaCase, month_bounds


@tagged('post_install', '-at_install')
class TestBooks(DeltaCase):

    def test_demo_books(self):
        """Test 1: the demo is loaded; local profit and balances match the oracle."""
        self.assertEqual(self.dataset_sha256, self.expected['dataset_sha256'],
                         'seeds changed: run python docs/oracle.py')
        self.assertEqual(set(self.companies), set(self.data['companies']))
        for key, company in self.companies.items():
            self.assertEqual(company.currency_id.name, self.data['companies'][key]['currency'])
            self.assertFalse(company.country_id)
        self.assertEqual(len(self.moves), len(self.data['documents']))

        for month, per_company in self.expected['profit_local'].items():
            start, end = month_bounds(month)
            for key, expected in per_company.items():
                lines = self.posted_lines(self.companies[key], end, start).filtered(
                    lambda l: l.account_id.account_type.startswith(PL_PREFIXES))
                self.assertAmount(-sum(lines.mapped('balance')), expected, f'{key} profit {month}')

        for closing, per_company in self.expected['balance_local'].items():
            for key, expected in per_company.items():
                totals = defaultdict(float)
                for line in self.posted_lines(self.companies[key], closing):
                    totals[self.local_label(key, line)] += line.balance
                actual = {}
                for label, value in totals.items():
                    base = label.removesuffix(' (IC)')
                    spec = next((s for s in self.data['accounts'].values() if s['label'] == base), None)
                    sign = 1 if spec and spec['account_type'].startswith('asset') else -1
                    if round(value, 2):
                        actual[label] = round(sign * value, 2)
                self.assertEqual(set(actual), set(expected), f'{key} balance rows {closing}')
                for label, value in expected.items():
                    self.assertAmount(actual[label], value, f'{key} {label} {closing}')

    def test_cutoff_dates(self):
        """Test 2: accounting and invoice dates are exactly as in the seeds (cut-off traps)."""
        split_dates = 0
        for doc in self.data['documents']:
            move = self.moves[doc['id']]
            self.assertEqual(move.state, 'posted')
            if doc['type'] == 'entry':
                self.assertEqual(str(move.date), doc['date'], doc['id'])
            else:
                self.assertEqual(str(move.invoice_date), doc['invoice_date'], doc['id'])
                self.assertEqual(str(move.date), doc.get('date', doc['invoice_date']), doc['id'])
                split_dates += bool(doc.get('date') and doc['date'] != doc['invoice_date'])
        self.assertTrue(split_dates, 'the seeds must contain a document booked after its invoice date')
