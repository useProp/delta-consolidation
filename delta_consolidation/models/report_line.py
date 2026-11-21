"""Group report: the companies' books translated to the group currency plus the eliminations column."""
from collections import defaultdict
from datetime import date

from odoo import api, fields, models

from .elimination import PL_PREFIXES, TRANSIT_LABEL, month_end, month_start

CYE_LABEL = 'Current year earnings'
CTA_LABEL = 'CTA'
ELIM_ENTITY = 'Eliminations'
SECTIONS = ('income', 'expense', 'equity', 'asset', 'liability')


def section_of(account_type):
    return next(s for s in SECTIONS if account_type.startswith(s))


def natural_sign(section):
    """Sign that turns debit-minus-credit into the amount shown in the section."""
    return 1 if section in ('asset', 'expense') else -1


class ConsolReportLine(models.Model):
    _name = 'delta.consol.report.line'
    _description = 'Group report line'
    _order = 'statement desc, section_sequence, account_label, entity_sequence'

    group_id = fields.Many2one('delta.consol.group', required=True, ondelete='cascade', index=True)
    month = fields.Date(required=True, index=True, help='First day of the report month.')
    statement = fields.Selection([('pl', 'Profit and loss'), ('bs', 'Balance sheet')], required=True)
    section = fields.Selection([
        ('income', 'Income'), ('expense', 'Expenses'),
        ('asset', 'Assets'), ('liability', 'Liabilities'), ('equity', 'Equity'),
    ], required=True)
    section_sequence = fields.Integer()
    row_type = fields.Selection([
        ('account', 'Account'), ('transit', 'Cash in transit'),
        ('cye', 'Current year earnings'), ('cta', 'CTA'),
    ], required=True, default='account')
    account_id = fields.Many2one('account.account')
    account_label = fields.Char(string='Account', required=True)
    is_intercompany = fields.Boolean(string='Intercompany')
    entity = fields.Char(required=True, help='Company name, or Eliminations.')
    entity_sequence = fields.Integer()
    company_id = fields.Many2one('res.company', help='Empty on the eliminations column.')
    local_currency_id = fields.Many2one('res.currency', string='Local currency')
    amount_local = fields.Float(
        string='Amount (local)', aggregator=None,
        help='Company currency, natural sign. Not summed: the companies keep books in different currencies.')
    amount_usd = fields.Float(string='Amount (group)', help='Group currency, natural sign of the section.')
    balance_usd = fields.Float(string='Balance (group)', help='Debit minus credit, group currency.')

    # ---------------------------------------------------------------- engine
    @api.model
    def _translate(self, line, closing_date, group, partners=None):
        """A journal item's balance in the group currency (docs/SPEC.md, first matching rule).
        The only currency conversion in the module."""
        company = line.company_id
        target = group.currency_id
        if company.currency_id == target:
            return line.balance
        partners = partners if partners is not None else group._company_partners()
        if line.currency_id == target and self.env['delta.consol.elimination']._is_ic(line, partners):
            return line.amount_currency
        section = section_of(line.account_id.account_type)
        day = line.date if section in PL_PREFIXES + ('equity',) else closing_date
        return company.currency_id._convert(line.balance, target, company, day, round=False)

    @api.model
    def _report_rows(self, group, month):
        """Report rows for the month that contains `month` (a date): P&L for the month,
        balance sheet at the month end. Returns a list of create values."""
        start, end = month_start(month), month_end(month)
        Elimination = self.env['delta.consol.elimination']
        Elimination._ensure_entries(group, end)
        partners = group._company_partners()
        entity_seq = {c: i for i, c in enumerate(group.company_ids.sorted('id'), start=1)}
        pl, bs = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])   # key -> [local, usd]
        cta = defaultdict(float)

        lines = self.env['account.move.line'].with_context(
            allowed_company_ids=group.company_ids.ids).sudo().search([
                ('company_id', 'in', group.company_ids.ids),
                ('parent_state', '=', 'posted'),
                ('date', '<=', end),
            ])
        for line in lines:
            usd = self._translate(line, end, group, partners)
            section = section_of(line.account_id.account_type)
            is_ic = Elimination._is_ic(line, partners)
            cta[line.company_id] -= usd
            if section in PL_PREFIXES:
                if line.date >= start:
                    key = (line.company_id, section, 'account', line.account_id, is_ic)
                    pl[key][0] += line.balance
                    pl[key][1] += usd
                key = (line.company_id, 'equity', 'cye', None, False)
            else:
                key = (line.company_id, section, 'account', line.account_id, is_ic)
            bs[key][0] += line.balance
            bs[key][1] += usd
        for company, value in cta.items():
            if not company.currency_id.is_zero(value) and company.currency_id != group.currency_id:
                bs[(company, 'equity', 'cta', None, False)][1] += value

        elim_lines = self.env['delta.consol.elimination.line'].sudo().search([
            ('elimination_id.group_id', '=', group.id), ('date', '<=', end)])
        for line in elim_lines:
            if line.is_pl:
                section = section_of(line.account_type)
                if line.date >= start:
                    pl[(False, section, 'account', line.account_id, True)][1] += line.balance
                bs[(False, 'equity', 'cye', None, False)][1] += line.balance
            elif line.kind == 'transit':
                bs[(False, 'asset', 'transit', None, False)][1] += line.balance
            else:
                bs[(False, section_of(line.account_type), 'account', line.account_id, True)][1] += line.balance

        rows = []
        for statement, values in (('pl', pl), ('bs', bs)):
            for (company, section, row_type, account, is_ic), (local, usd) in values.items():
                sign = natural_sign(section)
                rows.append({
                    'group_id': group.id,
                    'month': start,
                    'statement': statement,
                    'section': section,
                    'section_sequence': SECTIONS.index(section),
                    'row_type': row_type,
                    'account_id': account.id if account else False,
                    'account_label': self._label(row_type, account, company or group.company_ids[:1]),
                    'is_intercompany': is_ic,
                    'entity': company.name if company else ELIM_ENTITY,
                    'entity_sequence': entity_seq.get(company, len(entity_seq) + 1),
                    'company_id': company.id if company else False,
                    'local_currency_id': company.currency_id.id if company else False,
                    'amount_local': sign * local if company else 0.0,
                    'amount_usd': sign * usd,
                    'balance_usd': usd,
                })
        return rows

    @api.model
    def _label(self, row_type, account, company):
        if row_type == 'transit':
            return TRANSIT_LABEL
        if row_type == 'cye':
            return CYE_LABEL
        if row_type == 'cta':
            return CTA_LABEL
        account = account.with_company(company)
        return f'{account.code} {account.name}'

    @api.model
    def _rebuild(self, group, month):
        """Replace the stored report lines of the group and month."""
        start = month_start(month)
        self.search([('group_id', '=', group.id), ('month', '=', start)]).unlink()
        return self.create(self._report_rows(group, start))
