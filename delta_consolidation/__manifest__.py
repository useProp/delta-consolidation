{
    'name': 'Delta Group Consolidation',
    'summary': 'Intercompany eliminations and USD group reporting for Delta Group',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'author': 'Delta Group',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/elimination_views.xml',
        'views/report_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': False,
}
