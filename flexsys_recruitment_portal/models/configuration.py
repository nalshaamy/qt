"""Company-bound settings for the standalone public recruitment portal.

Staged logo never becomes public until Publish Brand is pressed.
"""
import base64
import json
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from ..services.brand_engine import (TOKENS, InvalidLogo, apply_overrides,
                                      generate_palette, logo_fingerprint, safe_css)


class CareerConfiguration(models.Model):
    _name = 'flexsys.career.config'
    _description = 'FlexSys Recruitment Portal Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', default=lambda self: self.env.company)
    is_public_portal = fields.Boolean(compute='_compute_is_public_portal', string='Serving /careers')
    portal_enabled = fields.Boolean(default=True)
    application_enabled = fields.Boolean(default=True)
    default_talent_pool_id = fields.Many2one('hr.talent.pool', string='Default Talent Pool')
    max_cv_size = fields.Integer(default=5, string='Maximum CV (MiB)')
    allow_docx = fields.Boolean(default=False, help='Enable after approving malware screening controls. PDF-only by default.')
    auto_acknowledgment = fields.Boolean(default=True)
    privacy_version = fields.Char(default='1.0', required=True)
    privacy_text = fields.Text(default='We process the details you submit only to review your application for potential employment. Contact us to request access, correction or deletion where permitted by applicable law.', translate=True)
    hero_title = fields.Char(default='Join our team', translate=True)
    hero_description = fields.Text(default='We welcome general applications even when no positions are currently open.', translate=True)
    retention_months = fields.Integer(default=12, help='Proposed review period; requires legal approval before production retention policy is enforced.')
    brand_mode = fields.Selection([('automatic','Automatic'),('custom','Custom'),('overrides','Automatic with Overrides')], default='automatic', required=True)
    brand_logo = fields.Binary(attachment=True, string='Published Brand Logo')
    brand_logo_candidate = fields.Binary(attachment=True, string='Candidate Logo (Preview)')
    brand_draft_palette = fields.Text(readonly=True, string='Draft Palette (JSON)')
    brand_palette_json = fields.Text(readonly=True, string='Published Palette (JSON)')
    brand_manual_overrides = fields.Text(string='Manual Overrides JSON', default='{}', help='Object such as {"primary":"#123456"}; use exact hex colors.')
    brand_logo_hash = fields.Char(readonly=True)
    brand_revision = fields.Integer(default=0, readonly=True)
    brand_last_generated_at = fields.Datetime(readonly=True)

    _unique_company = models.Constraint('UNIQUE(company_id)', 'One careers configuration is allowed per company.')

    @api.constrains('company_id', 'default_talent_pool_id', 'max_cv_size', 'retention_months')
    def _check_settings(self):
        for config in self:
            if config.default_talent_pool_id and config.default_talent_pool_id.company_id != config.company_id:
                raise ValidationError('Talent pool belongs to another company.')
            if not 1 <= config.max_cv_size <= 10:
                raise ValidationError('CV size must be between 1 and 10 MiB.')
            if not 0 <= config.retention_months <= 120:
                raise ValidationError('Retention review period must be between 0 and 120 months.')

    def _compute_is_public_portal(self):
        selected = self.env['ir.config_parameter'].sudo().get_param(
            'flexsys_recruitment_portal.public_config_id')
        for record in self:
            record.is_public_portal = str(record.id) == str(selected)

    def action_set_public_portal(self):
        """Select the company serving /careers for the *whole database*.

        One hostname/path cannot infer the destination company from arbitrary
        browser-supplied IDs. Store the selection on the server instead.
        """
        self.ensure_one()
        if not self.env.user.has_group('flexsys_recruitment_portal.group_career_manager'):
            from odoo.exceptions import AccessError
            raise AccessError('Only Careers Managers may change the public portal company.')
        if self.company_id not in self.env.companies:
            from odoo.exceptions import AccessError
            raise AccessError('The selected company is not permitted for this user.')
        self.env['ir.config_parameter'].sudo().set_param(
            'flexsys_recruitment_portal.public_config_id', str(self.id))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _override_map(self):
        self.ensure_one()
        try:
            overrides = json.loads(self.brand_manual_overrides or '{}')
            if not isinstance(overrides, dict):
                raise ValueError('Overrides must be an object.')
            if set(overrides) - set(TOKENS):
                raise ValueError('Unknown token.')
            return overrides
        except (ValueError, TypeError) as exc:
            raise UserError('Brand overrides must be a JSON object mapping token names to hex colors.') from exc

    def action_preview_brand(self):
        for config in self:
            raw = config.brand_logo_candidate or config.brand_logo or config.company_id.logo
            if not raw:
                raise UserError('Upload a logo first.')
            try:
                palette = generate_palette(base64.b64decode(raw))
                if config.brand_mode == 'custom':
                    palette = apply_overrides(palette, config._override_map())
                elif config.brand_mode == 'overrides':
                    palette = apply_overrides(palette, config._override_map())
            except (InvalidLogo, ValueError) as exc:
                raise UserError(str(exc)) from exc
            config.brand_draft_palette = json.dumps(palette, indent=2, sort_keys=True)
        return True

    def action_publish_brand(self):
        for config in self:
            if not config.brand_draft_palette:
                raise UserError('Generate and review the draft brand before publishing.')
            palette = json.loads(config.brand_draft_palette)
            safe_css(palette)
            if config.brand_logo_candidate:
                config.brand_logo = config.brand_logo_candidate
                config.brand_logo_candidate = False
            published = config.brand_logo or config.company_id.logo
            config.write({
                'brand_palette_json': json.dumps(palette, sort_keys=True),
                'brand_draft_palette': False,
                'brand_logo_hash': logo_fingerprint(base64.b64decode(published)) if published else False,
                'brand_revision': config.brand_revision + 1,
                'brand_last_generated_at': fields.Datetime.now(),
            })
        return True

    def action_open_brand_preview(self):
        self.ensure_one()
        if not self.brand_draft_palette:
            raise UserError('Generate the brand preview first.')
        return {'type': 'ir.actions.act_url', 'url': '/careers/brand-preview/%s' % self.id,
                'target': 'new'}

    def action_setup_pool(self):
        for config in self:
            if not config.default_talent_pool_id:
                config.default_talent_pool_id = self.env['hr.talent.pool'].with_company(config.company_id).create({
                    'name': '%s — General Applications' % config.company_id.name,
                    'company_id': config.company_id.id,
                })
        return True

    def public_palette(self):
        self.ensure_one()
        if self.brand_palette_json:
            try:
                palette = json.loads(self.brand_palette_json)
                safe_css(palette)
                return palette
            except (ValueError, KeyError, TypeError):
                pass
        return generate_palette_fallback()


def generate_palette_fallback():
    # Tiny safe in-memory logo; avoids runtime processing of a logo on repeated anonymous visits.
    from ..services.brand_engine import DEFAULT_PRIMARY, mix, readable
    primary = DEFAULT_PRIMARY
    return {'primary':primary, 'secondary': mix(primary,'#ffffff',.87), 'accent':mix(primary,'#101820',.26),
        'background':'#ffffff','surface':'#f6f8fb','text':'#17202c','text_secondary':'#4c5664',
        'on_primary':readable(primary),'button_hover':mix(primary,'#000000',.16), 'border':'#737f8b',
        'focus':primary,'success':'#166534','error':'#b42318'}
