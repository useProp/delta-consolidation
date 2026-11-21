"""Group report: the companies' books translated to the group currency plus the eliminations column."""
from collections import defaultdict
from datetime import date

from odoo import api, fields, models

from dateutil.relativedelta import relativedelta

from .elimination import AMOUNT_LINE_DOMAIN, PL_PREFIXES, TRANSIT_LABEL, month_end, month_start

CYE_LABEL = 'Current year earnings'
RE_LABEL = 'Retained earnings'
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
    user_id = fields.Many2one('res.users', required=True, index=True, default=lambda self: self.env.uid,
                              help='Who built the report: each user rebuilds only their own rows.')
    month = fields.Date(required=True, index=True, help='First day of the report month.')
    statement = fields.Selection([('pl', 'Profit and loss'), ('bs', 'Balance sheet')], required=True)
    section = fields.Selection([
        ('income', 'Income'), ('expense', 'Expenses'),
        ('asset', 'Assets'), ('liability', 'Liabilities'), ('equity', 'Equity'),
    ], required=True)
    section_sequence = fields.Integer()
    row_type = fields.Selection([
        ('account', 'Account'), ('transit', 'Cash in transit'),
        ('cye', 'Current year earnings'), ('re', 'Retained earnings'), ('cta', 'CTA'),
    ], required=True, default='account')
    account_id = fields.Many2one('account.account', string='Ledger account')
    account_label = fields.Char(string='Account', required=True)
    is_intercompany = fields.Boolean(string='Intercompany')
    entity = fields.Char(required=True, help='Company name, or Eliminations.')
    entity_sequence = fields.Integer()
    company_id = fields.Many2one('res.company', help='Empty on the eliminations column.')
    local_currency_id = fields.Many2one('res.currency', string='Local currency')
    amount_local = fields.Float(
        string='Amount (local)', aggregator=None,
        help='Company currency, same sign as Amount (group). Not summed: the companies keep books in different currencies.')
    amount_usd = fields.Float(
        string='Amount (group)',
        help='Group currency. P&L: profit contribution (income +, expense -); balance sheet: natural sign.')
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
    def _elimination_lines(self, group, end):
        """Elimination lines dated up to `end`, as dicts: the stored lines of posted entries and,
        for months without a posted entry, lines computed on the fly. Nothing is written."""
        Elimination = self.env['delta.consol.elimination'].sudo()
        first = self.env['account.move.line'].with_context(allowed_company_ids=group.company_ids.ids).sudo().search(
            [('company_id', 'in', group.company_ids.ids), ('parent_state', '=', 'posted')] + AMOUNT_LINE_DOMAIN,
            order='date', limit=1)
        result = []
        current = month_start(first.date) if first else month_start(end)
        while current <= end:
            entry = Elimination.search([('group_id', '=', group.id), ('date_from', '=', current),
                                        ('state', '=', 'posted')], limit=1)
            if entry:
                result += [{'date': l.date, 'company_id': l.company_id.id, 'account_id': l.account_id.id,
                            'kind': l.kind, 'balance': l.balance} for l in entry.line_ids]
            else:
                result += Elimination._compute_lines(group, current, month_end(current))[0]
            current += relativedelta(months=1)
        return result

    @api.model
    def _report_rows(self, group, month):
        """Report rows for the month that contains `month` (a date): P&L for the month,
        balance sheet at the month end. Returns a list of create values; writes nothing."""
        start, end = month_start(month), month_end(month)
        year_start = date(start.year, 1, 1)
        Elimination = self.env['delta.consol.elimination']
        partners = group._company_partners()
        entity_seq = {c: i for i, c in enumerate(group.company_ids.sorted('id'), start=1)}
        pl, bs = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])   # key -> [local, usd]
        label_company = {}
        cta = defaultdict(float)

        def earnings_key(company, day):
            return (company, 'equity', 'cye' if day >= year_start else 're', None, False)

        lines = self.env['account.move.line'].with_context(
            allowed_company_ids=group.company_ids.ids).sudo().search([
                ('company_id', 'in', group.company_ids.ids),
                ('parent_state', '=', 'posted'),
                ('date', '<=', end),
            ] + AMOUNT_LINE_DOMAIN)
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
                key = earnings_key(line.company_id, line.date)
            else:
                key = (line.company_id, section, 'account', line.account_id, is_ic)
            bs[key][0] += line.balance
            bs[key][1] += usd
        for company, value in cta.items():
            if not company.currency_id.is_zero(value) and company.currency_id != group.currency_id:
                bs[(company, 'equity', 'cta', None, False)][1] += value

        Account, Company = self.env['account.account'], self.env['res.company']
        for line in self._elimination_lines(group, end):
            account = Account.browse(line['account_id'])
            if line['kind'] == 'transit':
                bs[(False, 'asset', 'transit', None, False)][1] += line['balance']
                continue
            section = section_of(account.account_type)
            if section in PL_PREFIXES:
                if line['date'] >= start:
                    key = (False, section, 'account', account, True)
                    pl[key][1] += line['balance']
                    label_company.setdefault(key, Company.browse(line['company_id']))
                bs[earnings_key(False, line['date'])][1] += line['balance']
            else:
                key = (False, section, 'account', account, True)
                bs[key][1] += line['balance']
                label_company.setdefault(key, Company.browse(line['company_id']))

        rows = []
        for statement, values in (('pl', pl), ('bs', bs)):
            for key, (local, usd) in values.items():
                company, section, row_type, account, is_ic = key
                # P&L: profit contribution, so the statement total is the profit;
                # balance sheet: natural sign of the section (docs/SPEC.md, Report).
                sign = -1 if statement == 'pl' else natural_sign(section)
                rows.append({
                    'group_id': group.id,
                    'month': start,
                    'statement': statement,
                    'section': section,
                    'section_sequence': SECTIONS.index(section),
                    'row_type': row_type,
                    'account_id': account.id if account else False,
                    'account_label': self._label(row_type, account, company or label_company.get(key), is_ic),
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
    def _label(self, row_type, account, company, is_ic):
        if row_type == 'transit':
            return TRANSIT_LABEL
        if row_type == 'cye':
            return CYE_LABEL
        if row_type == 're':
            return RE_LABEL
        if row_type == 'cta':
            return CTA_LABEL
        # account.code is company-dependent: read it in the company of the (mirrored) line
        account = account.with_company(company or account.company_ids[:1])
        label = f'{account.code} {account.name}'
        return f'{label} (IC)' if is_ic else label

    @api.model
    def _rebuild(self, group, month, user):
        """Replace `user`'s stored report lines of the group and month."""
        start = month_start(month)
        self.search([('group_id', '=', group.id), ('month', '=', start), ('user_id', '=', user.id)]).unlink()
        return self.create([dict(vals, user_id=user.id) for vals in self._report_rows(group, start)])
