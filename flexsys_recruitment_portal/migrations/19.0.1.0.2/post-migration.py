"""Upgrade selection of the company serving the shared public careers route."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    param = env['ir.config_parameter'].sudo()
    key = 'flexsys_recruitment_portal.public_config_id'
    previous = param.get_param(key)
    Config = env['flexsys.career.config'].sudo()
    if previous and str(previous).isdigit() and Config.browse(int(previous)).exists():
        return
    config = Config.search([], order='id', limit=1)
    if config:
        param.set_param(key, str(config.id))
