from odoo import fields, models


class CareerSubmission(models.Model):
    _name = 'flexsys.career.submission'
    _description = 'Career Submission Idempotency Ledger'
    _rec_name = 'reference'
    _order = 'id desc'

    request_key = fields.Char(required=True, index=True, readonly=True, copy=False)
    applicant_id = fields.Many2one('hr.applicant', ondelete='restrict', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', readonly=True)
    reference = fields.Char(readonly=True)
    state = fields.Selection([('processing','Processing'),('completed','Completed')], default='processing', required=True, readonly=True)
    ip_hash = fields.Char(index=True, readonly=True)

    _request_unique = models.Constraint('UNIQUE(request_key)', 'Submission has already been recorded.')
