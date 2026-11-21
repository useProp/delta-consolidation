from odoo import fields, models
from odoo.exceptions import AccessError


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

    def _check_user_access(self):
        """The user must be allowed in every company of the group: the group view shows all their books."""
        if self.env.su:
            return
        missing = self.company_ids - self.env.user.company_ids
        if missing:
            raise AccessError(self.env._(
                'You need access to all companies of %(group)s to use it. Missing: %(companies)s.',
                group=', '.join(self.mapped('name')), companies=', '.join(missing.mapped('name'))))
