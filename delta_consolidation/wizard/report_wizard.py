from datetime import date

from odoo import api, fields, models

MONTHS = [(str(m), date(2000, m, 1).strftime('%B')) for m in range(1, 13)]


class ConsolReportWizard(models.TransientModel):
    _name = 'delta.consol.report.wizard'
    _description = 'Group report'

    group_id = fields.Many2one('delta.consol.group', required=True,
                               default=lambda self: self.env['delta.consol.group'].search([], limit=1))
    month = fields.Selection(MONTHS, required=True, default=lambda self: str(fields.Date.today().month))
    year = fields.Integer(required=True, default=lambda self: fields.Date.today().year)

    def _month_date(self):
        return date(self.year, int(self.month), 1)

    def action_open_report(self):
        self.ensure_one()
        start = self._month_date()
        # Report lines and missing draft eliminations are rebuilt as superuser, so the
        # read-only auditor can build the report; the books are only read.
        self.env['delta.consol.report.line'].sudo()._rebuild(self.group_id.sudo(), start)
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Group report %s', start.strftime('%B %Y')),
            'res_model': 'delta.consol.report.line',
            'view_mode': 'pivot,list',
            'domain': [('group_id', '=', self.group_id.id), ('month', '=', start)],
            'context': {'search_default_statement_pl': 0},
        }
