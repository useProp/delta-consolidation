"""Demo data loader. All values come from data/demo_dataset.json; this file holds none."""
import json
import logging

from odoo import Command, api, fields, models
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

DATASET_PATH = 'delta_consolidation/data/demo_dataset.json'
INVOICE_TYPES = ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')


class ConsolDemo(models.AbstractModel):
    _name = 'delta.consol.demo'
    _description = 'Delta Group demo data loader'

    @api.model
    def _dataset(self):
        with file_open(DATASET_PATH) as f:
            return json.load(f)

    # ------------------------------------------------------------ lookups
    @api.model
    def _companies(self, data):
        """{seed key: res.company} for companies that already exist."""
        Company = self.env['res.company'].sudo()
        result = {}
        for key, vals in data['companies'].items():
            company = Company.search([('name', '=', vals['name'])], limit=1)
            if company:
                result[key] = company
        return result

    @api.model
    def _currency(self, code):
        return self.env['res.currency'].with_context(active_test=False).search([('name', '=', code)], limit=1)

    @api.model
    def _general_journal(self, company):
        return self.env['account.journal'].search([
            ('company_id', '=', company.id),
            ('type', '=', 'general'),
            ('id', '!=', company.currency_exchange_journal_id.id),
        ], order='id', limit=1)

    @api.model
    def _account_map(self, company, data=None):
        """{seed account key: account.account} for one company."""
        data = data or self._dataset()
        Template = self.env['account.chart.template'].with_company(company)
        Account = self.env['account.account'].with_company(company)
        result = {}
        for key, spec in data['accounts'].items():
            if 'xmlid' in spec:
                result[key] = Template.ref(spec['xmlid'])
            elif spec.get('source') == 'bank_journal':
                journal = self.env['account.journal'].search(
                    [('company_id', '=', company.id), ('type', '=', 'bank')], order='id', limit=1)
                result[key] = journal.default_account_id
            elif 'create' in spec:
                result[key] = Account.search([
                    ('company_ids', 'in', company.id),
                    ('code', '=', spec['create']['code']),
                ], limit=1)
        return result

    # -------------------------------------------------------------- load
    @api.model
    def load(self):
        """Load the demo once. Returns {seed document id: account.move}, or False if already loaded."""
        data = self._dataset()
        if self._companies(data).get('US'):
            _logger.info('Delta demo data already loaded, nothing to do')
            return False
        self._load_rates(data)
        companies = self._load_companies(data)
        accounts = {key: self._load_accounts(company, data) for key, company in companies.items()}
        partners = self._load_partners(data, companies)
        self._load_users(data, companies)
        self._load_group(data, companies)
        moves = self._load_documents(data, companies, accounts, partners)
        self._load_eliminations(data)
        _logger.info('Delta demo data loaded')
        return moves

    @api.model
    def _load_rates(self, data):
        Rate = self.env['res.currency.rate'].sudo()
        for code, table in data['rates_per_usd'].items():
            currency = self._currency(code)
            currency.active = True
            for day, rate in table.items():
                Rate.create({'currency_id': currency.id, 'name': day, 'rate': rate, 'company_id': False})

    @api.model
    def _load_companies(self, data):
        companies = {}
        Template = self.env['account.chart.template']
        for key, vals in data['companies'].items():
            currency = self._currency(vals['currency'])
            currency.active = True
            company = self.env['res.company'].create({'name': vals['name'], 'currency_id': currency.id})
            Template.try_loading('generic_coa', company=company, install_demo=False)
            # generic_coa writes the fiscal country (US) and its currency on the company;
            # restore the seed currency and keep the company without a country (ASSUMPTIONS.md).
            company.write({'currency_id': currency.id, 'country_id': False})
            companies[key] = company
        return companies

    @api.model
    def _load_accounts(self, company, data):
        Account = self.env['account.account'].with_company(company)
        for spec in data['accounts'].values():
            if 'create' in spec:
                Account.create({
                    'code': spec['create']['code'],
                    'name': spec['create']['name'],
                    'account_type': spec['account_type'],
                    'is_intercompany': spec.get('is_intercompany', False),
                    'company_ids': [Command.set(company.ids)],
                })
        accounts = self._account_map(company, data)
        for key in data['accounts']:
            if key not in accounts:
                raise ValueError(f'account {key} not resolved for {company.name}')
        flagged = [k for k, s in data['accounts'].items() if s.get('is_intercompany')]
        for key in flagged:
            accounts[key].is_intercompany = True
        return accounts

    @api.model
    def _load_partners(self, data, companies):
        partners = {key: company.partner_id for key, company in companies.items()}
        for key, vals in data['partners'].items():
            partners[key] = self.env['res.partner'].create({
                'name': vals['name'],
                'company_id': companies[vals['company']].id,
            })
        return partners

    @api.model
    def _load_users(self, data, companies):
        admin = self.env.ref('base.user_admin')
        admin.write({'company_ids': [Command.link(companies[k].id) for k in data['admin_companies']]})
        for vals in data['users']:
            user_companies = [companies[k] for k in vals['companies']]
            groups = [self.env.ref('base.group_user')] + [self.env.ref(g) for g in vals['groups']]
            self.env['res.users'].with_context(no_reset_password=True).create({
                'login': vals['login'],
                'password': vals['password'],
                'name': vals['name'],
                'company_id': user_companies[0].id,
                'company_ids': [Command.set([c.id for c in user_companies])],
                'groups_id': [Command.set([g.id for g in groups])],
            })

    @api.model
    def _load_group(self, data, companies):
        return self.env['delta.consol.group'].create({
            'name': data['group']['name'],
            'company_ids': [Command.set([c.id for c in companies.values()])],
            'currency_id': self._currency(data['group']['currency']).id,
        })

    @staticmethod
    def _accounting_date(doc):
        return doc.get('date') or doc['invoice_date']

    @api.model
    def _load_documents(self, data, companies, accounts, partners):
        moves = {}
        docs = sorted(data['documents'], key=self._accounting_date)   # stable: seed order within a day
        for doc in docs:
            company = companies[doc['company']]
            if doc['type'] == 'entry':
                vals = self._entry_vals(doc, company, accounts[doc['company']], partners)
            elif doc['type'] in INVOICE_TYPES:
                vals = self._invoice_vals(doc, company, accounts[doc['company']], partners, moves)
            else:
                raise ValueError(f"unknown document type {doc['type']}")
            move = self.env['account.move'].with_company(company).create(vals)
            move.action_post()
            if doc.get('reverses'):
                # Linked only after posting: posting a credit note with reversed_entry_id
                # auto-reconciles it with the invoice and books an exchange difference
                # (ASSUMPTIONS.md, implementation decisions).
                move.reversed_entry_id = moves[doc['reverses']]
            moves[doc['id']] = move
        return moves

    @api.model
    def _entry_vals(self, doc, company, accounts, partners):
        lines = []
        for line in doc['lines']:
            currency = self._currency(line['currency']) if line.get('currency') else company.currency_id
            amount_currency = line['amount_currency'] if line.get('currency') else line['balance']
            lines.append(Command.create({
                'account_id': accounts[line['account']].id,
                'name': doc['ref'],
                'balance': line['balance'],
                'currency_id': currency.id,
                'amount_currency': amount_currency,
                'partner_id': partners[line['partner']].id if line.get('partner') else False,
            }))
        return {
            'move_type': 'entry',
            'journal_id': self._general_journal(company).id,
            'date': doc['date'],
            'ref': doc['ref'],
            'line_ids': lines,
        }

    @api.model
    def _invoice_vals(self, doc, company, accounts, partners, moves):
        vals = {
            'move_type': doc['type'],
            'partner_id': partners[doc['partner']].id,
            'currency_id': self._currency(doc['currency']).id,
            'invoice_date': doc['invoice_date'],
            'date': self._accounting_date(doc),
            'invoice_line_ids': [Command.create({
                'name': line['name'],
                'account_id': accounts[line['account']].id,
                'quantity': 1,
                'price_unit': line['amount'],
                'tax_ids': [Command.clear()],
            }) for line in doc['lines']],
        }
        return vals

    @api.model
    def _load_eliminations(self, data):
        """Generate the elimination entries listed in the seeds (needs the engine, step 3)."""
        if 'delta.consol.elimination' not in self.env:
            return
        group = self.env['delta.consol.group'].search([('name', '=', data['group']['name'])], limit=1)
        Elimination = self.env['delta.consol.elimination']
        for state in ('posted', 'draft'):
            for month in data['eliminations'].get(state, []):
                entry = Elimination._get_or_create(group, fields.Date.to_date(f'{month}-01'))
                entry.action_generate()
                if state == 'posted':
                    entry.action_post()
