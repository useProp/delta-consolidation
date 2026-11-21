import hashlib
import json
from datetime import date, timedelta

from odoo.tests import TransactionCase
from odoo.tools import file_open

DATASET = 'delta_consolidation/data/demo_dataset.json'
EXPECTED = 'delta_consolidation/tests/expected_figures.json'
PL_PREFIXES = ('income', 'expense')
CYE = 'Current year earnings'


def month_bounds(month):
    year, mon = map(int, month.split('-'))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1) - timedelta(days=1)
    return start, end


class DeltaCase(TransactionCase):
    """Loads the demo once per class and exposes the seeds and the expected figures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with file_open(DATASET, 'rb') as f:
            raw = f.read()
        cls.dataset_sha256 = hashlib.sha256(raw).hexdigest()
        cls.data = json.loads(raw)
        with file_open(EXPECTED) as f:
            cls.expected = json.load(f)
        cls.moves = cls.env['delta.consol.demo'].load()
        Demo = cls.env['delta.consol.demo']
        cls.companies = Demo._companies(cls.data)
        cls.accounts = {key: Demo._account_map(c, cls.data) for key, c in cls.companies.items()}
        cls.group = cls.env['delta.consol.group'].search([('name', '=', cls.data['group']['name'])])
        cls.all_companies_env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=[c.id for c in cls.companies.values()]))

    def assertAmount(self, value, expected, msg=None):
        self.assertAlmostEqual(value, expected, delta=0.01, msg=msg)

    def posted_lines(self, company, date_to, date_from=None):
        domain = [('company_id', '=', company.id), ('parent_state', '=', 'posted'), ('date', '<=', date_to)]
        if date_from:
            domain.append(('date', '>=', date_from))
        return self.all_companies_env['account.move.line'].search(domain)

    def local_label(self, company_key, line):
        """Seed label of a journal item, as used by the oracle for local balances."""
        for key, account in self.accounts[company_key].items():
            if account == line.account_id:
                spec = self.data['accounts'][key]
                break
        else:
            raise AssertionError(f'account {line.account_id.display_name} is not in the seeds')
        if spec['account_type'].startswith(PL_PREFIXES):
            return CYE
        others = {c.partner_id for k, c in self.companies.items() if k != company_key}
        is_ic = line.partner_id in others and (
            spec['account_type'] in ('asset_receivable', 'liability_payable') or spec.get('is_intercompany'))
        return spec['label'] + (' (IC)' if is_ic else '')

    # ------------------------------------------------------------ helpers
    def company_key(self, company):
        return next(k for k, c in self.companies.items() if c == company)

    def entry(self, month):
        start, _end = month_bounds(month)
        return self.env['delta.consol.elimination'].search(
            [('group_id', '=', self.group.id), ('date_from', '=', start)])

    def seed_label(self, company_key, account):
        for key, acc in self.accounts[company_key].items():
            if acc == account:
                return self.data['accounts'][key]['label']
        raise AssertionError(f'account {account.display_name} is not in the seeds')
