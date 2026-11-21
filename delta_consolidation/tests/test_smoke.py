from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSmoke(TransactionCase):
    def test_module_installed(self):
        module = self.env['ir.module.module'].search([('name', '=', 'delta_consolidation')])
        self.assertEqual(module.state, 'installed')
