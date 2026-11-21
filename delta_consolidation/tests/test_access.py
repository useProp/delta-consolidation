from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import DeltaCase, month_bounds


@tagged('post_install', '-at_install')
class TestAccess(DeltaCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        login = cls.data['users'][0]['login']
        cls.auditor = cls.env['res.users'].search([('login', '=', login)])

    def test_admin_has_full_accounting(self):
        """admin can open the module's menus after the demo load (Community default lacks the group)."""
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('account.group_account_user'))
        for key in self.data['admin_companies']:
            self.assertIn(self.companies[key], admin.company_ids)

    def test_auditor_reads_entries(self):
        """The read-only auditor opens entries and lines but cannot change them."""
        self.assertTrue(self.auditor.has_group('account.group_account_readonly'))
        self.assertFalse(self.auditor.has_group('account.group_account_user'))
        month = self.data['eliminations']['posted'][-1]
        entry = self.entry(month).with_user(self.auditor)
        self.assertTrue(entry.line_ids)
        self.assertTrue(entry.reconciliation_html)
        draft = self.entry(self.data['eliminations']['draft'][0]).with_user(self.auditor)
        self.assertTrue(draft.line_ids)
        with self.assertRaises(AccessError):
            draft.line_ids[:1].write({'balance': 1.0})
        with self.assertRaises(AccessError):
            draft.action_generate()
        with self.assertRaises(AccessError):
            entry.write({'state': 'draft'})

    def test_auditor_builds_report(self):
        """The auditor builds the group report through the wizard (report lines rebuilt via sudo)."""
        month = self.data['eliminations']['posted'][-1]
        start, _end = month_bounds(month)
        wizard = self.env['delta.consol.report.wizard'].with_user(self.auditor).create({
            'group_id': self.group.id, 'month': str(start.month), 'year': str(start.year)})
        action = wizard.action_open_report()
        lines = self.env['delta.consol.report.line'].with_user(self.auditor).search(action['domain'])
        self.assertTrue(lines)
        profit = sum(l.amount_usd for l in lines if l.statement == 'pl')
        self.assertAmount(profit, self.expected['profit_usd'][month]['GROUP'])

    def test_open_source(self):
        """Every elimination line opens its source journal entry in the right company."""
        entry = self.entry(self.data['eliminations']['posted'][-1])
        admin = self.env.ref('base.user_admin')
        for line in entry.line_ids:
            # active company differs from the source's company, as in the UI
            other = next(c for c in self.companies.values() if c != line.company_id)
            action = line.with_user(admin).with_context(allowed_company_ids=[other.id]).action_open_source()
            self.assertEqual(action['res_model'], 'account.move')
            self.assertEqual(action['res_id'], line.source_line_id.move_id.id)
            self.assertIn(line.source_line_id.company_id.id, action['context']['allowed_company_ids'])
