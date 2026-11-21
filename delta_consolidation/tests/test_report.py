from collections import defaultdict
from datetime import date

from odoo.tests import tagged

from .common import DeltaCase, month_bounds

ROW_LABELS = {'transit': 'IC cash in transit', 'cye': 'Current year earnings', 'cta': 'CTA'}


@tagged('post_install', '-at_install')
class TestReport(DeltaCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Report = cls.env['delta.consol.report.line']
        cls.rows = {month: Report._report_rows(cls.group, month_bounds(month)[0])
                    for month in cls.expected['profit_usd']}

    def entity_key(self, row):
        if not row['company_id']:
            return 'ELIM'
        return self.company_key(self.env['res.company'].browse(row['company_id']))

    def oracle_label(self, row):
        if row['row_type'] in ROW_LABELS:
            return ROW_LABELS[row['row_type']]
        account = self.env['account.account'].browse(row['account_id'])
        company = self.env['res.company'].browse(row['company_id']) if row['company_id'] else None
        keys = [self.company_key(company)] if company else list(self.companies)
        for key in keys:
            for seed_key, acc in self.accounts[key].items():
                if acc == account:
                    return self.data['accounts'][seed_key]['label']
        raise AssertionError(f'account {account.display_name} is not in the seeds')

    def test_group_pl(self):
        """Test 9: monthly profit per entity and for the group, external revenue, year to date."""
        ytd = 0.0
        for month, expected in self.expected['profit_usd'].items():
            pl = [r for r in self.rows[month] if r['statement'] == 'pl']
            profit = defaultdict(float)
            for row in pl:
                profit[self.entity_key(row)] += row['amount_usd']
            for entity, value in expected.items():
                if entity == 'GROUP':
                    continue
                self.assertAmount(profit[entity], value, f'{entity} profit {month}')
            group_profit = sum(profit.values())
            self.assertAmount(group_profit, expected['GROUP'], f'group profit {month}')
            external = sum(r['amount_usd'] for r in pl
                           if r['section'] == 'income' and not r['is_intercompany'] and r['company_id'])
            self.assertAmount(external, self.expected['external_revenue_usd'][month], f'external revenue {month}')
            ytd += group_profit
            self.assertAmount(ytd, self.expected['group_profit_ytd_usd'][month], f'group YTD {month}')
            # The P&L of the companies matches their books in local currency
            for key, value in self.expected['profit_local'][month].items():
                local = sum(r['amount_local'] for r in pl if r['company_id'] == self.companies[key].id)
                self.assertAmount(local, value, f'{key} local profit {month}')

    def test_group_bs(self):
        """Test 10: balance sheet per entity and for the group at every month end."""
        for closing, expected in self.expected['balance_sheet_usd'].items():
            rows = [r for r in self.rows[closing[:7]] if r['statement'] == 'bs']
            actual = defaultdict(float)
            totals = defaultdict(float)
            for row in rows:
                entity = self.entity_key(row)
                key = (self.oracle_label(row), row['is_intercompany'])
                actual[(key, entity)] += row['amount_usd']
                actual[(key, 'GROUP')] += row['amount_usd']
                bucket = 'assets' if row['section'] == 'asset' else 'liabilities_equity'
                totals[(bucket, entity)] += row['amount_usd']
                totals[(bucket, 'GROUP')] += row['amount_usd']
                totals[('balance', entity)] += row['balance_usd']
            expected_keys = set()
            for exp in expected['rows']:
                key = (exp['label'], exp['intercompany'])
                expected_keys.add(key)
                for entity in ('US', 'UA', 'PL', 'ELIM', 'GROUP'):
                    self.assertAmount(actual[(key, entity)], exp[entity], f'{closing} {key} {entity}')
                if exp['intercompany']:
                    self.assertAmount(actual[(key, 'GROUP')], 0.0, f'{closing} {key} not eliminated')
            for (key, entity), value in actual.items():
                if key not in expected_keys:
                    self.assertAmount(value, 0.0, f'{closing} unexpected row {key} {entity}')
            for bucket, values in expected['totals'].items():
                for entity, value in values.items():
                    self.assertAmount(totals[(bucket, entity)], value, f'{closing} {bucket} {entity}')
            for entity in ('US', 'UA', 'PL', 'ELIM'):
                self.assertAmount(totals[('balance', entity)], 0.0, f'{closing} balance_usd {entity}')

    def test_report_wizard(self):
        """The wizard stores the rows and the pivot total equals the group figures."""
        month = max(self.expected['profit_usd'])
        start, end = month_bounds(month)
        wizard = self.env['delta.consol.report.wizard'].create({
            'group_id': self.group.id, 'month': str(start.month), 'year': str(start.year)})
        action = wizard.action_open_report()
        lines = self.env['delta.consol.report.line'].search(action['domain'])
        self.assertEqual(len(lines), len(self.rows[month]))
        self.assertAmount(sum(lines.filtered(lambda l: l.statement == 'bs').mapped('balance_usd')), 0.0)
        self.assertAmount(sum(lines.filtered(lambda l: l.statement == 'pl').mapped('amount_usd')),
                          self.expected['profit_usd'][month]['GROUP'], 'pivot P&L total = group profit')
        self.assertNotIn('False', ' '.join(lines.mapped('account_label')))
        for label in set(lines.filtered('is_intercompany').mapped('account_label')):
            same = lines.filtered(lambda l: l.account_label == label and l.statement == 'bs')
            self.assertAmount(sum(same.mapped('amount_usd')), 0.0, f'{label}: IC row not zero in the group')
        wizard.action_open_report()
        self.assertEqual(self.env['delta.consol.report.line'].search_count(action['domain']), len(lines))

    def test_company_pl_untouched(self):
        """The standard P&L of a company still shows its own books: no elimination in account.move."""
        for key, company in self.companies.items():
            for month, value in self.expected['profit_local'].items():
                start, end = month_bounds(month)
                lines = self.posted_lines(company, end, start).filtered(
                    lambda l: l.account_id.account_type.startswith(('income', 'expense')))
                self.assertAmount(-sum(lines.mapped('balance')), value[key], f'{key} {month}')
