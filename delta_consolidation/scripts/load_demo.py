# Run with: odoo shell -d delta --no-http < scripts/load_demo.py
env['delta.consol.demo'].load()
env.cr.commit()
