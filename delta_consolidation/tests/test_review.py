"""Regression tests for the independent review findings (docs/AI_WORKFLOW.md)."""
from collections import defaultdict
from datetime import date

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import DeltaCase, month_bounds


@tagged('post_install', '-at_install')
class TestReviewFindings(DeltaCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Report = cls.env['delta.consol.report.line']
        cls.Elimination = cls.env['delta.consol.elimination']
        cls.draft_month = cls.data['eliminations']['draft'][0]
        cls.draft_start, cls.draft_end = month_bounds(cls.draft_month)
        cls.usd = cls.group.currency_id
        # a seller with non-USD books invoicing the USD parent, as in the seeds
        cls.seller = next(k for k, c in cls.data['companies'].items() if c['currency'] != cls.data['group']['currency'])
        cls.buyer = next(k for k, c in cls.data['companies'].items() if c['currency'] == cls.data['group']['currency'])

    def ic_invoice(self, day, amount, extra_lines=()):
        company = self.companies[self.seller]
        invoice = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice',
            'partner_id': self.companies[self.buyer].partner_id.id,
            'currency_id': self.usd.id,
            'invoice_date': day, 'date': day,
            'invoice_line_ids': list(extra_lines) + [Command.create({
                'name': 'Review test', 'quantity': 1, 'price_unit': amount,
                'account_id': self.accounts[self.seller]['income'].id, 'tax_ids': [Command.clear()]})],
        })
        invoice.action_post()
        return invoice

    def bs_check(self, rows):
        """Every entity balances and every intercompany row is zero in the group column."""
        balance, ic = defaultdict(float), defaultdict(float)
        for row in rows:
            if row['statement'] == 'bs':
                balance[row['entity']] += row['balance_usd']
                if row['is_intercompany']:
                    ic[row['account_label']] += row['amount_usd']
        for entity, value in balance.items():
            self.assertAmount(value, 0.0, f'{entity} does not balance')
        for label, value in ic.items():
            self.assertAmount(value, 0.0, f'{label} not eliminated')

    def test_section_and_note_lines(self):
        """Finding 1: invoices with section and note lines do not break generation or the report."""
        entry = self.entry(self.draft_month)
        before = entry.line_count
        invoice = self.ic_invoice(self.draft_start, 100, extra_lines=[
            Command.create({'display_type': 'line_section', 'name': 'Section'}),
            Command.create({'display_type': 'line_note', 'name': 'Note'}),
        ])
        self.assertTrue(invoice.line_ids.filtered(lambda l: l.display_type == 'line_section').partner_id,
                        'section lines carry the intercompany partner')
        entry.action_generate()
        self.assertEqual(entry.line_count, before + 2, 'revenue and receivable mirrored, section/note ignored')
        self.bs_check(self.Report._report_rows(self.group, self.draft_start))

    def test_user_without_all_companies(self):
        """Finding 2: a user missing one group company sees nothing of the group and cannot build it."""
        company = self.companies[self.buyer]
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'login': 'one_company_accountant', 'name': 'One-company accountant',
            'company_id': company.id, 'company_ids': [Command.set(company.ids)],
            'groups_id': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('account.group_account_user').id])],
        })
        self.assertFalse(self.env['delta.consol.group'].with_user(user).search([]))
        self.assertFalse(self.Elimination.with_user(user).search([]))
        self.assertFalse(self.env['delta.consol.elimination.line'].with_user(user).search([]))
        with self.assertRaises(AccessError):
            self.group.with_user(user)._check_user_access()
        with self.assertRaises(AccessError):
            self.entry(self.draft_month).with_user(user).action_generate()

    def test_exchange_difference_after_reconciliation(self):
        """Finding 3 (kept as designed): an exchange difference from reconciling an intercompany
        invoice with its receipt is not eliminated, is group profit, and leaves IC rows at zero."""
        group_partners = self.group._company_partners()
        receipt = next(m for m in self.moves.values()
                       if m.move_type == 'entry' and m.date >= self.draft_start
                       and m.company_id.currency_id != self.usd
                       and any(l.partner_id.id in group_partners and l.account_id.account_type == 'asset_receivable'
                               for l in m.line_ids))
        company = receipt.company_id
        receipt_line = receipt.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
        invoice_line = self.all_companies_env['account.move.line'].search([
            ('company_id', '=', company.id), ('parent_state', '=', 'posted'),
            ('move_id.move_type', '=', 'out_invoice'), ('account_id', '=', receipt_line.account_id.id),
            ('partner_id', '=', receipt_line.partner_id.id),
            ('amount_currency', '=', -receipt_line.amount_currency)], order='date', limit=1)
        before = len(self.Elimination._compute_lines(self.group, self.draft_start, self.draft_end)[0])
        (invoice_line | receipt_line).with_company(company).reconcile()
        exchange = self.all_companies_env['account.move.line'].search([
            ('company_id', '=', company.id), ('journal_id', '=', company.currency_exchange_journal_id.id)])
        self.assertTrue(exchange, 'reconciliation at a different rate books an exchange difference')
        self.assertEqual(len(self.Elimination._compute_lines(self.group, self.draft_start, self.draft_end)[0]),
                         before, 'exchange differences are not eliminated')
        rows = self.Report._report_rows(self.group, self.draft_start)
        self.bs_check(rows)
        gain = -sum(self.Report._translate(l, self.draft_end, self.group)
                    for l in exchange.filtered(lambda l: l.account_id.account_type.startswith(('income', 'expense'))))
        self.assertTrue(gain)
        profit = sum(r['amount_usd'] for r in rows if r['statement'] == 'pl' and r['company_id'] == company.id)
        self.assertAmount(profit, self.expected['profit_usd'][self.draft_month][self.company_key(company)] + gain)

    def test_prior_year_activity(self):
        """Finding 4: activity before 1 January goes to retained earnings and is eliminated too."""
        first_month = min(self.expected['profit_usd'])
        start, end = month_bounds(first_month)
        prior = date(start.year - 1, 12, 31)
        company = self.companies[self.buyer]
        bill = self.env['account.move'].with_company(company).create({
            'move_type': 'in_invoice', 'partner_id': self.companies[self.seller].partner_id.id,
            'currency_id': self.usd.id, 'invoice_date': prior, 'date': prior,
            'invoice_line_ids': [Command.create({
                'name': 'Prior-year intercompany service', 'quantity': 1, 'price_unit': 700,
                'account_id': self.accounts[self.buyer]['cost_of_goods_sold'].id, 'tax_ids': [Command.clear()]})],
        })
        bill.action_post()
        rows = self.Report._report_rows(self.group, start)
        self.bs_check(rows)
        bs = [r for r in rows if r['statement'] == 'bs']
        retained = {r['entity']: r['amount_usd'] for r in bs if r['row_type'] == 're'}
        self.assertAmount(retained[company.name], -700)
        self.assertAmount(retained['Eliminations'], 700)
        cye = sum(r['amount_usd'] for r in bs if r['row_type'] == 'cye')
        self.assertAmount(cye, self.expected['group_profit_ytd_usd'][first_month], 'current year unchanged')
        profit = sum(r['amount_usd'] for r in rows if r['statement'] == 'pl')
        self.assertAmount(profit, self.expected['profit_usd'][first_month]['GROUP'])

    def test_post_regenerates_and_freezes(self):
        """Findings 5 and 6: posting includes documents booked after Generate; the posted entry keeps
        the reconciliation it was posted with."""
        entry = self.entry(self.draft_month)
        entry.action_generate()
        before = entry.line_count
        self.ic_invoice(self.draft_start, 100)
        entry.action_post()
        self.assertEqual(entry.line_count, before + 2)
        frozen = entry.reconciliation_html
        self.assertTrue(frozen)
        self.ic_invoice(self.draft_start, 100)
        entry.invalidate_recordset()
        self.assertEqual(entry.reconciliation_html, frozen)

    def test_report_writes_no_entries(self):
        """Finding 7: building the report creates or changes no elimination entry; users keep their own rows."""
        self.entry(self.draft_month).unlink()
        snapshot = sorted(self.Elimination.search([]).mapped(lambda e: (e.id, e.write_date)))
        rows = self.Report._report_rows(self.group, self.draft_start)
        self.assertEqual(sorted(self.Elimination.search([]).mapped(lambda e: (e.id, e.write_date))), snapshot)
        profit = sum(r['amount_usd'] for r in rows if r['statement'] == 'pl')
        self.assertAmount(profit, self.expected['profit_usd'][self.draft_month]['GROUP'],
                          'unposted month computed on the fly')
        auditor = self.env['res.users'].search([('login', '=', self.data['users'][0]['login'])])
        admin = self.env.ref('base.user_admin')
        mine = self.Report.sudo()._rebuild(self.group, self.draft_start, admin)
        theirs = self.Report.sudo()._rebuild(self.group, self.draft_start, auditor)
        self.assertTrue(mine.exists() and theirs.exists())
        self.assertFalse(self.Report.with_user(auditor).search([('id', 'in', mine.ids)]))

    def test_posted_entry_locked(self):
        """Finding 8: header, group deletion and moving lines into a posted entry are blocked."""
        posted = self.entry(self.data['eliminations']['posted'][0])
        draft = self.entry(self.draft_month)
        with self.assertRaises(UserError):
            posted.write({'date_from': posted.date_from, 'exception_line_ids': [Command.clear()]})
        with self.assertRaises(UserError):
            draft.line_ids[:1].write({'elimination_id': posted.id})
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self.group.unlink()
