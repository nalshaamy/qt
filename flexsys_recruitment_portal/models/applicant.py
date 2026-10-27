from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    flexsys_career_is_general = fields.Boolean(string='General Application', index=True, copy=False)
    flexsys_career_reference = fields.Char(string='Career Reference', index=True, readonly=True, copy=False)
    flexsys_career_category_id = fields.Many2one('flexsys.career.category', string='Desired Career')
    flexsys_career_city = fields.Char(string='City')
    flexsys_career_experience_years = fields.Integer(string='Experience (Years)')
    flexsys_career_status = fields.Selection([
        ('new', 'New'), ('review', 'Under Review'), ('shortlisted', 'Shortlisted'),
        ('pool', 'Talent Pool'), ('transferred', 'Transferred'), ('closed', 'Closed'),
    ], default='new', string='General Application Status', tracking=True)
    flexsys_career_resume_id = fields.Many2one('ir.attachment', string='Curriculum Vitae', copy=False, groups='hr_recruitment.group_hr_recruitment_user')
    flexsys_career_privacy_version = fields.Char(string='Privacy Notice Version', readonly=True)
    flexsys_career_acknowledged_at = fields.Datetime(string='Privacy Notice Acknowledged At', readonly=True)
    flexsys_career_retention_until = fields.Date(string='Retention Review Date')
    flexsys_career_source = fields.Selection([('web', 'Careers Website'), ('other', 'Other')], default='web')
    flexsys_career_duplicate_candidate = fields.Boolean(string='Possible Duplicate', readonly=True)
    flexsys_career_education = fields.Selection([
        ('secondary', 'Secondary'), ('diploma', 'Diploma'),
        ('bachelor', 'Bachelor'), ('masters', 'Masters'), ('doctorate', 'Doctorate'),
    ], string='Education Level')

    _career_reference_unique = models.Constraint('UNIQUE(flexsys_career_reference)', 'Career reference must be unique.')

    @api.constrains('flexsys_career_is_general', 'company_id', 'talent_pool_ids')
    def _check_general_pool_company(self):
        for applicant in self.filtered('flexsys_career_is_general'):
            if any(pool.company_id and pool.company_id != applicant.company_id for pool in applicant.talent_pool_ids):
                raise ValidationError('General application cannot belong to another company talent pool.')
