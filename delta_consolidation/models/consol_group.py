from odoo import fields, models


class ConsolGroup(models.Model):
    _name = 'delta.consol.group'
    _description = 'Consolidation group'

    name = fields.Char(required=True)
    company_ids = fields.Many2many('res.company', string='Companies', required=True)
    currency_id = fields.Many2one('res.currency', string='Reporting currency', required=True)

    def _company_partners(self):
        """{res.partner id: res.company} for the group companies."""
        self.ensure_one()
        return {c.partner_id.id: c for c in self.company_ids}
