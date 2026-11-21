from odoo import fields, models


class AccountAccount(models.Model):
    _inherit = 'account.account'

    is_intercompany = fields.Boolean(
        string='Intercompany',
        help='Balance-sheet account used only for intercompany balances (e.g. loans). '
             'Lines on it with a group-company partner are eliminated in the group view.',
    )
