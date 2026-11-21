"""Monthly elimination entries. They live in the module's own tables, never in account.move."""
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

PL_PREFIXES = ('income', 'expense')
BS_IC_TYPES = ('asset_receivable', 'liability_payable')
TRANSIT_LABEL = 'IC cash in transit'
# Journal items that carry amounts: no section/note lines, no off-balance accounts
AMOUNT_LINE_DOMAIN = [
    ('display_type', 'not in', ('line_section', 'line_note')),
    ('account_id.account_type', '!=', 'off_balance'),
]
POSTED_EDITABLE_FIELDS = {'state', 'reconciliation_frozen'}


def month_start(day):
    return date(day.year, day.month, 1)


def month_end(day):
    return month_start(day) + relativedelta(months=1, days=-1)


class ConsolElimination(models.Model):
    _name = 'delta.consol.elimination'
    _description = 'Elimination entry'
    _order = 'date_from desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    group_id = fields.Many2one('delta.consol.group', required=True, ondelete='restrict')
    currency_id = fields.Many2one(related='group_id.currency_id')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted')], default='draft', required=True)
    line_ids = fields.One2many('delta.consol.elimination.line', 'elimination_id', string='Lines')
    line_count = fields.Integer(compute='_compute_totals', store=True)
    debit_total = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id')
    credit_total = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id')
    pl_effect = fields.Monetary(
        compute='_compute_totals', store=True, currency_field='currency_id',
        string='Effect on profit', help='Change of group profit caused by this entry.')
    transit_total = fields.Monetary(compute='_compute_totals', store=True, currency_field='currency_id',
                                    string='Cash in transit')
    exception_line_ids = fields.Many2many(
        'account.move.line', 'delta_consol_elimination_exception_rel', string='Exceptions',
        help='Intercompany journal items that are not in the group currency and were not eliminated.')
    exception_count = fields.Integer(compute='_compute_exception_count')
    generated_on = fields.Datetime(readonly=True)
    reconciliation_frozen = fields.Html(sanitize=False, readonly=True, copy=False,
                                        help='Counterparty reconciliation as it was when the entry was posted.')
    reconciliation_html = fields.Html(compute='_compute_reconciliation_html', sanitize=False,
                                      string='Counterparty reconciliation')

    @api.depends('date_from')
    def _compute_name(self):
        for entry in self:
            entry.name = entry.date_from and entry.date_from.strftime('ELIM/%Y/%m') or '/'

    @api.depends('line_ids.balance', 'line_ids.kind', 'line_ids.account_type')
    def _compute_totals(self):
        for entry in self:
            lines = entry.line_ids
            entry.line_count = len(lines)
            entry.debit_total = sum(b for b in lines.mapped('balance') if b > 0)
            entry.credit_total = -sum(b for b in lines.mapped('balance') if b < 0)
            entry.pl_effect = -sum(lines.filtered(lambda l: l.is_pl).mapped('balance'))
            entry.transit_total = sum(lines.filtered(lambda l: l.kind == 'transit').mapped('balance'))

    @api.depends('exception_line_ids')
    def _compute_exception_count(self):
        for entry in self:
            entry.exception_count = len(entry.exception_line_ids)

    @api.constrains('group_id', 'date_from', 'date_to')
    def _check_period(self):
        for entry in self:
            if entry.date_from != month_start(entry.date_from) or entry.date_to != month_end(entry.date_from):
                raise ValidationError(self.env._('An elimination entry covers exactly one calendar month.'))
            if self.search_count([('group_id', '=', entry.group_id.id), ('date_from', '=', entry.date_from),
                                  ('id', '!=', entry.id)]):
                raise ValidationError(self.env._('There is already an elimination entry for %s.', entry.name))

    def write(self, vals):
        if set(vals) - POSTED_EDITABLE_FIELDS and any(e.state == 'posted' for e in self):
            raise UserError(self.env._('A posted elimination entry cannot be changed: reset it to draft first.'))
        return super().write(vals)

    def unlink(self):
        if any(e.state == 'posted' for e in self):
            raise UserError(self.env._('A posted elimination entry cannot be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------ API
    @api.model
    def _get_or_create(self, group, day):
        start = month_start(day)
        entry = self.search([('group_id', '=', group.id), ('date_from', '=', start)], limit=1)
        return entry or self.create({'group_id': group.id, 'date_from': start, 'date_to': month_end(start)})

    @api.model
    def _is_ic(self, line, partners):
        """True if the journal item is intercompany (docs/SPEC.md). `partners`: group._company_partners()."""
        counterparty = partners.get(line.partner_id.id)
        if not counterparty or counterparty == line.company_id:
            return False
        account = line.account_id
        if account.account_type.startswith(PL_PREFIXES):
            return line.journal_id != line.company_id.currency_exchange_journal_id
        return account.account_type in BS_IC_TYPES or account.is_intercompany

    @api.model
    def _ic_lines(self, group, date_from, date_to):
        """Intercompany journal items of the group dated within the period.

        Returns (lines to eliminate, exception lines). See docs/SPEC.md, "Intercompany line"."""
        partners = group._company_partners()
        companies = group.company_ids
        candidates = self.env['account.move.line'].with_context(
            allowed_company_ids=companies.ids,
        ).sudo().search([
            ('company_id', 'in', companies.ids),
            ('parent_state', '=', 'posted'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('partner_id', 'in', list(partners)),
        ] + AMOUNT_LINE_DOMAIN, order='date, move_id, id')
        lines = exceptions = candidates.browse()
        for line in candidates:
            if not self._is_ic(line, partners):
                continue
            if line.currency_id.is_zero(line.amount_currency):
                continue        # exchange-difference lines carry no nominal
            if line.currency_id != group.currency_id:
                exceptions |= line
                continue
            lines |= line
        return lines, exceptions

    @api.model
    def _compute_lines(self, group, date_from, date_to):
        """Elimination line values for the period, without storing anything.
        Returns (list of line values, exception journal items)."""
        partners = group._company_partners()
        lines, exceptions = self._ic_lines(group, date_from, date_to)
        vals, by_move = [], defaultdict(lambda: self.env['account.move.line'])
        for line in lines:
            by_move[line.move_id] |= line
        for move_lines in by_move.values():
            for line in move_lines:
                vals.append(self._line_vals(line, partners, 'mirror', -line.amount_currency))
            total = sum(move_lines.mapped('amount_currency'))
            if not group.currency_id.is_zero(total):
                vals.append(self._line_vals(move_lines[0], partners, 'transit', total))
        if not group.currency_id.is_zero(sum(v['balance'] for v in vals)):
            raise UserError(self.env._('Eliminations %s – %s are not balanced.', date_from, date_to))
        return vals, exceptions

    @api.model
    def _line_vals(self, line, partners, kind, balance):
        return {
            'kind': kind,
            'name': line.name if kind == 'mirror' else TRANSIT_LABEL,
            'date': line.date,
            'company_id': line.company_id.id,
            'counterparty_company_id': partners[line.partner_id.id].id,
            'account_id': line.account_id.id if kind == 'mirror' else False,
            'source_line_id': line.id,
            'balance': balance,
        }

    def action_generate(self):
        for entry in self:
            if entry.state == 'posted':
                raise UserError(self.env._('%s is posted: reset it to draft before regenerating.', entry.name))
            entry.group_id._check_user_access()
            vals, exceptions = self._compute_lines(entry.group_id, entry.date_from, entry.date_to)
            entry.line_ids.unlink()
            entry.write({
                'line_ids': [fields.Command.create(v) for v in vals],
                'exception_line_ids': [fields.Command.set(exceptions.ids)],
                'generated_on': fields.Datetime.now(),
            })
        return True

    def action_post(self):
        """Regenerate from the current books, then lock, so a post never locks stale lines."""
        for entry in self.filtered(lambda e: e.state == 'draft'):
            entry.action_generate()
            entry.write({'state': 'posted', 'reconciliation_frozen': entry._reconciliation_markup()})
        return True

    def action_draft(self):
        self.group_id._check_user_access()
        self.write({'state': 'draft', 'reconciliation_frozen': False})
        return True

    def action_open_exceptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Exceptions'),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.exception_line_ids.ids)],
            'context': {'allowed_company_ids': self.group_id.company_ids.ids},
        }

    # ---------------------------------------------- counterparty reconciliation
    def _ic_reconciliation(self):
        """Per seller -> buyer pair, cumulative to the entry's month end, USD nominal (live books)."""
        self.ensure_one()
        group = self.group_id
        year_start = date(self.date_to.year, 1, 1)
        lines, _exceptions = self._ic_lines(group, year_start, self.date_to)
        partners = group._company_partners()
        totals = defaultdict(float)
        pairs = set()
        for line in lines:
            company, partner = line.company_id, partners[line.partner_id.id]
            account_type = line.account_id.account_type
            bucket = next((p for p in PL_PREFIXES if account_type.startswith(p)), account_type)
            if bucket == 'income':
                pairs.add((company, partner))
            totals[(company, partner, bucket)] += line.amount_currency
        result = []
        for seller, buyer in sorted(pairs, key=lambda p: (p[0].name, p[1].name)):
            row = {
                'seller': seller, 'buyer': buyer,
                'seller_receivable': totals[(seller, buyer, 'asset_receivable')],
                'buyer_payable': -totals[(buyer, seller, 'liability_payable')],
                'seller_revenue': -totals[(seller, buyer, 'income')],
                'buyer_expense': totals[(buyer, seller, 'expense')],
            }
            row['balance_difference'] = row['seller_receivable'] - row['buyer_payable']
            row['pl_difference'] = row['seller_revenue'] - row['buyer_expense']
            result.append(row)
        return result

    def _reconciliation_markup(self):
        self.ensure_one()
        fmt = '{:,.2f}'.format
        head = ['Pair', 'Seller receivable', 'Buyer payable', 'Difference',
                'Seller revenue', 'Buyer expense', 'Difference']
        rows = Markup('').join(
            Markup('<tr><td>%s</td>%s</tr>') % (
                f"{r['seller'].name} → {r['buyer'].name}",
                Markup('').join(Markup('<td class="text-end">%s</td>') % fmt(r[k]) for k in (
                    'seller_receivable', 'buyer_payable', 'balance_difference',
                    'seller_revenue', 'buyer_expense', 'pl_difference')))
            for r in self._ic_reconciliation())
        return Markup(
            '<p>Cumulative from 1 January to %s, %s nominal, as of %s. A non-zero difference is a '
            'document one side has booked and the other has not yet (cut-off, cash in transit).</p>'
            '<table class="table table-sm"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
        ) % (self.date_to, self.currency_id.name, fields.Datetime.now(),
             Markup('').join(Markup('<th>%s</th>') % escape(h) for h in head), rows)

    @api.depends('date_to', 'group_id', 'line_ids', 'state', 'reconciliation_frozen')
    def _compute_reconciliation_html(self):
        for entry in self:
            if entry.state == 'posted' and entry.reconciliation_frozen:
                entry.reconciliation_html = entry.reconciliation_frozen
            elif entry.date_to and entry.group_id:
                entry.reconciliation_html = entry._reconciliation_markup()
            else:
                entry.reconciliation_html = False


class ConsolEliminationLine(models.Model):
    _name = 'delta.consol.elimination.line'
    _description = 'Elimination line'
    _order = 'date, id'

    elimination_id = fields.Many2one('delta.consol.elimination', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='elimination_id.currency_id')
    kind = fields.Selection([('mirror', 'Mirror'), ('transit', 'Cash in transit')], required=True)
    name = fields.Char(string='Label')
    date = fields.Date(required=True)
    company_id = fields.Many2one('res.company', required=True)
    counterparty_company_id = fields.Many2one('res.company', string='Counterparty', required=True)
    account_id = fields.Many2one('account.account', string='Account')
    account_type = fields.Selection(related='account_id.account_type', store=True)
    is_pl = fields.Boolean(compute='_compute_is_pl', store=True)
    source_line_id = fields.Many2one('account.move.line', string='Source journal item',
                                     required=True, ondelete='restrict', index=True)
    source_move_id = fields.Many2one(related='source_line_id.move_id', string='Source document')
    balance = fields.Monetary(currency_field='currency_id', help='Debit minus credit, group currency.')
    debit = fields.Monetary(compute='_compute_debit_credit', currency_field='currency_id')
    credit = fields.Monetary(compute='_compute_debit_credit', currency_field='currency_id')

    @api.depends('account_type')
    def _compute_is_pl(self):
        for line in self:
            line.is_pl = bool(line.account_type) and line.account_type.startswith(PL_PREFIXES)

    @api.depends('balance')
    def _compute_debit_credit(self):
        for line in self:
            line.debit = max(line.balance, 0.0)
            line.credit = max(-line.balance, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_editable()
        return lines

    def write(self, vals):
        self._check_editable()
        result = super().write(vals)
        self._check_editable()          # also blocks moving a line into a posted entry
        return result

    def unlink(self):
        self._check_editable()
        return super().unlink()

    def _check_editable(self):
        if any(line.elimination_id.state == 'posted' for line in self):
            raise UserError(self.env._('Lines of a posted elimination entry cannot be changed.'))

    def action_open_source(self):
        self.ensure_one()
        # The source belongs to another company than the active one, by design: read the
        # reference as superuser; the user's own access rights still apply to the opened form.
        move = self.sudo().source_line_id.move_id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'context': {'allowed_company_ids': (move.company_id | self.elimination_id.group_id.company_ids).ids},
        }
