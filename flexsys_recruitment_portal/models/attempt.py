from datetime import timedelta
from odoo import api, fields, models


class CareerAttempt(models.Model):
    _name = 'flexsys.career.attempt'
    _description = 'Private career submission attempt rate limiting'
    _order = 'id desc'
    _rec_name = 'ip_hash'
    ip_hash = fields.Char(required=True, index=True)
    company_id = fields.Many2one('res.company', required=True, ondelete='cascade')

    @api.model
    def _cron_purge_old_attempts(self):
        threshold = fields.Datetime.now() - timedelta(days=2)
        self.sudo().search([('create_date', '<', fields.Datetime.to_string(threshold))], limit=3000).unlink()
