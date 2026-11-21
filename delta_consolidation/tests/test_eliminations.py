from collections import defaultdict

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import DeltaCase, month_bounds

INVOICE_SIGN = {'out_invoice': 1, 'out_refund': -1, 'in_invoice': -1, 'in_refund': 1}


@tagged('post_install', '-at_install')
class TestEliminations(DeltaCase):

    def books_snapshot(self):
        lines = self.all_companies_env['account.move.line'].search(
            [('company_id', 'in', self.group.company_ids.ids)])
        totals = defaultdict(float)
        for line in lines:
            totals[(line.company_id.id, line.account_id.id)] += line.balance
        return len(lines), {k: round(v, 2) for k, v in totals.items()}

    def test_demo_entry_states(self):
        """The loader creates the entries listed in the seeds, in the listed state."""
        for state, months in self.data['eliminations'].items():
            for month in months:
                entry = self.entry(month)
                self.assertEqual(len(entry), 1, month)
                self.assertEqual(entry.state, state, month)
                self.assertEqual(entry.name, 'ELIM/' + month.replace('-', '/'))

    def test_books_untouched(self):
        """Test 3: generating eliminations does not create or change journal items."""
        before = self.books_snapshot()
        moves_before = self.all_companies_env['account.move'].search_count([])
        for month in self.expected['eliminations']:
            entry = self.entry(month)
            entry.action_draft()
            entry.action_generate()
            entry.action_post()
        self.assertEqual(self.books_snapshot(), before)
        self.assertEqual(self.all_companies_env['account.move'].search_count([]), moves_before)

    def test_entries_balanced(self):
        """Test 4: line count, debit = credit, balance sums to zero."""
        for month, expected in self.expected['eliminations'].items():
            entry = self.entry(month)
            self.assertEqual(entry.line_count, expected['lines'], month)
            self.assertAmount(entry.debit_total, expected['debit'], f'{month} debit')
            self.assertAmount(entry.credit_total, expected['credit'], f'{month} credit')
            self.assertAmount(sum(entry.line_ids.mapped('balance')), 0.0, f'{month} balance')
            for line in entry.line_ids.filtered(lambda l: l.kind == 'mirror'):
                self.assertEqual(line.balance, -line.source_line_id.amount_currency)
                self.assertEqual(line.account_id, line.source_line_id.account_id)
                self.assertEqual(line.company_id, line.source_line_id.company_id)
                self.assertEqual(line.date, line.source_line_id.date)

    def test_cutoff_invoice(self):
        """Test 5: the cut-off moves profit between months; the cumulative effect is zero."""
        total = 0.0
        for month, expected in self.expected['eliminations'].items():
            entry = self.entry(month)
            self.assertAmount(entry.pl_effect, expected['pl_effect'], month)
            total += entry.pl_effect
        self.assertAmount(total, 0.0)
        self.assertTrue(any(e['pl_effect'] for e in self.expected['eliminations'].values()),
                        'the seeds must contain a cut-off difference')

    def test_credit_note(self):
        """Test 6: the credit note reduces the elimination of the pair in its month."""
        for doc in self.data['documents']:
            if not doc.get('reverses') or doc['type'] != 'out_refund':
                continue
            seller, buyer, month = doc['company'], doc['partner'], doc['invoice_date'][:7]
            start, end = month_bounds(month)
            # USD revenue the seller invoiced to the buyer in that month, net of credit notes (seeds)
            expected = sum(INVOICE_SIGN[d['type']] * l['amount']
                           for d in self.data['documents']
                           if d['type'] in INVOICE_SIGN and d['company'] == seller and d['partner'] == buyer
                           and start.isoformat() <= d.get('date', d['invoice_date']) <= end.isoformat()
                           for l in d['lines'])
            refunded = sum(l['amount'] for l in doc['lines'])
            lines = self.entry(month).line_ids.filtered(lambda l: l.kind == 'mirror' and l.is_pl)
            revenue = sum(lines.filtered(lambda l: l.company_id == self.companies[seller]
                                         and l.counterparty_company_id == self.companies[buyer]).mapped('balance'))
            expense = -sum(lines.filtered(lambda l: l.company_id == self.companies[buyer]
                                          and l.counterparty_company_id == self.companies[seller]).mapped('balance'))
            self.assertAmount(revenue, expected, 'seller revenue eliminated')
            self.assertAmount(expense, expected, 'buyer expense eliminated')
            refund_lines = lines.filtered(lambda l: l.source_move_id == self.moves[doc['id']])
            self.assertAmount(sum(refund_lines.mapped('balance')), -refunded, 'credit note mirrored with its sign')

    def test_payment_in_transit(self):
        """Test 7: cash in transit appears at the month end and clears the next month."""
        for closing, expected in self.expected['transit_usd'].items():
            entries = self.env['delta.consol.elimination'].search(
                [('group_id', '=', self.group.id), ('date_to', '<=', closing)])
            self.assertAmount(sum(entries.mapped('transit_total')), expected, closing)
        self.assertTrue(any(self.expected['transit_usd'].values()), 'the seeds must contain cash in transit')

    def test_loan(self):
        """Test 8: the loan is removed on both sides and leaves no cash in transit."""
        lines = self.env['delta.consol.elimination.line'].search([
            ('elimination_id.group_id', '=', self.group.id), ('kind', '=', 'mirror'),
            ('account_id.is_intercompany', '=', True)])
        self.assertTrue(lines)
        rows = self.expected['balance_sheet_usd']
        closing = max(rows)
        for row in rows[closing]['rows']:
            if row['label'].startswith('IC loan'):
                sign = 1 if row['section'] == 'asset' else -1
                side = lines.filtered(lambda l: self.seed_label(self.company_key(l.company_id), l.account_id)
                                      == row['label'])
                self.assertAmount(sign * sum(side.mapped('balance')), row['ELIM'], row['label'])
        loan_moves = lines.source_move_id
        transit = self.env['delta.consol.elimination.line'].search([
            ('kind', '=', 'transit'), ('source_move_id', 'in', loan_moves.ids)])
        self.assertAmount(sum(transit.mapped('balance')), 0.0)

    def test_ic_reconciliation(self):
        """Test 11: counterparty differences are explained per pair."""
        for closing, pairs in self.expected['ic_reconciliation_usd'].items():
            entry = self.entry(closing[:7])
            actual = {f"{self.company_key(r['seller'])}->{self.company_key(r['buyer'])}": r
                      for r in entry._ic_reconciliation()}
            self.assertEqual(set(actual), {p['pair'] for p in pairs}, closing)
            for pair in pairs:
                for field in ('seller_receivable', 'buyer_payable', 'seller_revenue', 'buyer_expense'):
                    self.assertAmount(actual[pair['pair']][field], pair[field], f"{closing} {pair['pair']} {field}")
            self.assertTrue(entry.reconciliation_html)

    def test_idempotent(self):
        """Test 12: regeneration is stable; a posted entry is locked."""
        draft = self.entry(self.data['eliminations']['draft'][0])

        def signature(entry):
            return sorted((l.kind, l.source_line_id.id, l.account_id.id, l.balance) for l in entry.line_ids)
        before = signature(draft)
        draft.action_generate()
        draft.action_generate()
        self.assertEqual(signature(draft), before)

        posted = self.entry(self.data['eliminations']['posted'][0])
        with self.assertRaises(UserError):
            posted.action_generate()
        with self.assertRaises(UserError):
            posted.line_ids[:1].balance = 1.0
        with self.assertRaises(UserError):
            posted.unlink()

    def test_non_usd_exception(self):
        """Test 13: an intercompany invoice outside the group currency is listed, not eliminated."""
        draft = self.entry(self.data['eliminations']['draft'][0])
        seller = next(k for k, c in self.data['companies'].items() if c['currency'] != self.data['group']['currency'])
        buyer = next(k for k in self.data['companies'] if k != seller)
        company = self.companies[seller]
        invoice = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice',
            'partner_id': self.companies[buyer].partner_id.id,
            'currency_id': company.currency_id.id,
            'invoice_date': draft.date_from,
            'date': draft.date_from,
            'invoice_line_ids': [Command.create({
                'name': 'Non-USD intercompany test', 'quantity': 1, 'price_unit': 1000,
                'account_id': self.accounts[seller]['income'].id, 'tax_ids': [Command.clear()]})],
        })
        invoice.action_post()
        lines_before = draft.line_count
        draft.action_generate()
        self.assertEqual(draft.exception_line_ids.move_id, invoice)
        self.assertEqual(draft.line_count, lines_before)
