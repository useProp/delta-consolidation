from datetime import date

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MONTHS = [(str(m), date(2000, m, 1).strftime('%B')) for m in range(1, 13)]


class ConsolReportWizard(models.TransientModel):
    _name = 'delta.consol.report.wizard'
    _description = 'Group report'

    group_id = fields.Many2one('delta.consol.group', required=True,
                               default=lambda self: self.env['delta.consol.group'].search([], limit=1))
    month = fields.Selection(MONTHS, required=True, default=lambda self: str(fields.Date.today().month))
    # Char, not Integer: the web client would show 2026 as "2,026"
    year = fields.Char(required=True, size=4, default=lambda self: str(fields.Date.today().year))

    @api.constrains('year')
    def _check_year(self):
        for wizard in self:
            if not (wizard.year.isdigit() and len(wizard.year) == 4):
                raise ValidationError(self.env._('Enter the year as four digits, e.g. 2026.'))

    def _month_date(self):
        return date(int(self.year), int(self.month), 1)

    def action_open_report(self):
        self.ensure_one()
        start = self._month_date()
        self.group_id._check_user_access()
        # Only the user's own report lines are written, as superuser, so the read-only auditor
        # can build the report. Eliminations of unposted months are computed, not stored.
        self.env['delta.consol.report.line'].sudo()._rebuild(self.group_id.sudo(), start, self.env.user)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Group report %s', start.strftime('%B %Y')),
            'res_model': 'delta.consol.report.line',
            'view_mode': 'pivot,list',
            'domain': [('group_id', '=', self.group_id.id), ('month', '=', start), ('user_id', '=', self.env.uid)],
        }
