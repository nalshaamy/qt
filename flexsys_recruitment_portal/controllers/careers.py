"""Public careers routes: narrow allowlist and controlled privileged writes."""
import base64
import json
from datetime import timedelta
from dateutil.relativedelta import relativedelta
import hashlib
import hmac
import logging
import re
from uuid import UUID, uuid4

from markupsafe import escape
from psycopg2 import IntegrityError
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request
from ..services.brand_engine import safe_css
from ..services.validators import (InvalidSubmission, clean_text, experience_years,
                                   normalize_email, normalize_phone, validate_document)

_logger = logging.getLogger(__name__)


class CareersController(http.Controller):

    def _config(self):
        website = request.website
        return request.env['flexsys.career.config'].sudo().search([
            ('website_id', '=', website.id),
            ('company_id', '=', website.company_id.id),
        ], limit=1)

    def _ctx(self, config, **values):
        context = dict(config=config, brand_css=safe_css(config.public_palette()),
                       request_key=str(uuid4()), language=request.env.lang or 'en_US')
        context.update(values)
        return context

    @http.route('/careers', type='http', auth='public', website=True, methods=['GET'], sitemap=True)
    def careers_index(self, **kw):
        config = self._config()
        if not config or not config.portal_enabled:
            raise NotFound()
        return request.render('flexsys_recruitment_portal.careers_home', self._ctx(config))

    @http.route('/careers/apply', type='http', auth='public', website=True, methods=['GET'], sitemap=True)
    def careers_apply(self, **kw):
        config = self._config()
        if not config or not config.portal_enabled:
            raise NotFound()
        categories = request.env['flexsys.career.category'].sudo().search([
            ('company_id', '=', config.company_id.id), ('active', '=', True)], order='sequence, name')
        return request.render('flexsys_recruitment_portal.careers_apply',
                              self._ctx(config, categories=categories, error=False, data={}))

    @http.route('/careers/privacy', type='http', auth='public', website=True, methods=['GET'], sitemap=True)
    def careers_privacy(self, **kw):
        config = self._config()
        if not config or not config.portal_enabled:
            raise NotFound()
        return request.render('flexsys_recruitment_portal.careers_privacy', self._ctx(config))

    @http.route('/careers/logo', type='http', auth='public', website=True, methods=['GET'], sitemap=False)
    def careers_logo(self, **kw):
        config = self._config()
        if not config or not config.portal_enabled:
            raise NotFound()
        logo = config.brand_logo or config.company_id.logo
        if not logo:
            raise NotFound()
        raw = base64.b64decode(logo)
        mime = 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else ('image/webp' if raw.startswith(b'RIFF') and raw[8:12] == b'WEBP' else 'image/png')
        return request.make_response(raw, headers=[
            ('Content-Type', mime), ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'public, max-age=3600'),
        ])

    @http.route('/careers/success', type='http', auth='public', website=True, methods=['GET'], sitemap=False)
    def careers_success(self, **kw):
        config = self._config()
        if not config or not config.portal_enabled:
            raise NotFound()
        # No personal information is exposed. Reference alone is not an access token.
        ref = str(kw.get('ref') or '')
        if not re.fullmatch(r'CR-\d{4}-\d{6,9}', ref):
            ref = ''
        return request.render('flexsys_recruitment_portal.careers_success',
                              self._ctx(config, reference=ref))

    def _remote_hash(self, company):
        # Do not trust an arbitrary client-provided X-Forwarded-For header.
        remote = request.httprequest.remote_addr or 'unknown'
        secret = request.env['ir.config_parameter'].sudo().get_param('database.secret') or request.env.cr.dbname
        digest = hmac.new(str(secret).encode(), ('careers:%d:%s' % (company.id, remote)).encode(), hashlib.sha256)
        return digest.hexdigest()

    def _rate_limit(self, config, ip_hash):
        attempts = request.env['flexsys.career.attempt'].sudo()
        cutoff = fields.Datetime.now() - timedelta(minutes=30)
        domain = [('company_id', '=', config.company_id.id), ('ip_hash', '=', ip_hash),
                  ('create_date', '>=', fields.Datetime.to_string(cutoff))]
        if attempts.search_count(domain) >= 20:
            return True
        attempts.create({'company_id': config.company_id.id, 'ip_hash': ip_hash})
        submissions = request.env['flexsys.career.submission'].sudo()
        return submissions.search_count(domain) >= 5

    def _render_error(self, config, message, status=400, form=None):
        categories = request.env['flexsys.career.category'].sudo().search([
            ('company_id', '=', config.company_id.id), ('active', '=', True)])
        # Do not re-echo sensitive submitted form values in response or log.
        response = request.render('flexsys_recruitment_portal.careers_apply',
                                  self._ctx(config, categories=categories, error=message, data={}))
        response.status_code = status
        return response

    @http.route('/careers/brand-preview/<int:config_id>', type='http', auth='user', website=True,
                methods=['GET'], sitemap=False)
    def careers_brand_preview(self, config_id, **kw):
        if not request.env.user.has_group('flexsys_recruitment_portal.group_career_manager'):
            raise NotFound()
        config = request.env['flexsys.career.config'].browse(config_id).exists()
        if not config or config.company_id not in request.env.companies or not config.brand_draft_palette:
            raise NotFound()
        try:
            palette = json.loads(config.brand_draft_palette)
            css = safe_css(palette)
        except (ValueError, KeyError, TypeError):
            raise NotFound()
        return request.render('flexsys_recruitment_portal.careers_brand_preview', {
            'config': config, 'brand_css': css,
        })

    @http.route('/careers/brand-preview/<int:config_id>/logo', type='http', auth='user', website=True,
                methods=['GET'], sitemap=False)
    def careers_brand_preview_logo(self, config_id, **kw):
        if not request.env.user.has_group('flexsys_recruitment_portal.group_career_manager'):
            raise NotFound()
        config = request.env['flexsys.career.config'].browse(config_id).exists()
        if not config or config.company_id not in request.env.companies:
            raise NotFound()
        logo = config.brand_logo_candidate or config.brand_logo or config.company_id.logo
        if not logo:
            raise NotFound()
        raw = base64.b64decode(logo)
        mime = 'image/png'
        if raw.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif raw.startswith(b'RIFF') and raw[8:12] == b'WEBP':
            mime = 'image/webp'
        return request.make_response(raw, headers=[('Content-Type', mime),
                                                   ('X-Content-Type-Options', 'nosniff')])

    @http.route('/careers/submit', type='http' , auth='public', website=True,
                methods=['POST'], csrf=True, sitemap=False)
    def careers_submit(self, **form):
        config = self._config()
        if not config or not config.portal_enabled:
            raise NotFound()
        if not config.application_enabled:
            return self._render_error(config, 'Applications are temporarily closed.', 403)
        if form.get('website_url'):  # honeypot
            return self._render_error(config, 'Unable to submit application.')
        ip_hash = self._remote_hash(config.company_id)
        try:
            request_key = str(UUID(str(form.get('request_key') or '')))
            if len(request_key) != 36:
                raise ValueError()
        except (ValueError, AttributeError):
            return self._render_error(config, 'Reload the form and try again.')

        pool = config.default_talent_pool_id
        if not pool or pool.company_id != config.company_id:
            _logger.error('Careers talent pool is missing for website %s', config.website_id.id)
            return self._render_error(config, 'Service temporarily unavailable.', 503)
        ledger = request.env['flexsys.career.submission'].sudo()
        existing = ledger.search([('request_key', '=', request_key), ('company_id', '=', config.company_id.id)], limit=1)
        if existing and existing.state == 'completed':
            return request.redirect('/careers/success?ref=%s' % existing.reference, code=303)
        if existing:
            return self._render_error(config, 'Request already being processed.')
        if self._rate_limit(config, ip_hash):
            return self._render_error(config, 'Too many applications. Please try again later.', 429)

        try:
            name = clean_text(form.get('name'), limit=120)
            phone = normalize_phone(form.get('phone'))
            email = normalize_email(form.get('email'))
            city = clean_text(form.get('city'), limit=80)
            years = experience_years(form.get('experience'))
            education = str(form.get('education') or '')
            if education not in ('secondary', 'diploma', 'bachelor', 'masters', 'doctorate'):
                raise InvalidSubmission('Invalid education value.')
            if str(form.get('privacy_ack') or '') != 'yes':
                raise InvalidSubmission('Privacy notice acknowledgment is required.')
            notes = clean_text(form.get('notes'), limit=1500, required=False)
            category_id = int(form.get('category_id') or 0)
            category = request.env['flexsys.career.category'].sudo().search([
                ('id', '=', category_id), ('company_id', '=', config.company_id.id),
                ('active', '=', True)], limit=1)
            if not category:
                raise InvalidSubmission('Invalid career category.')
            uploaded = request.httprequest.files.get('cv')
            if not uploaded:
                raise InvalidSubmission('Please attach your CV.')
            max_bytes = config.max_cv_size * 1024 * 1024
            raw = uploaded.stream.read(max_bytes + 1)
            allowed = ('pdf', 'docx') if config.allow_docx else ('pdf',)
            mime = validate_document(uploaded.filename, raw, max_bytes=max_bytes, allowed=allowed)
        except (ValueError, InvalidSubmission, TypeError, OverflowError):
            return self._render_error(config, 'Please verify the required fields and CV format.')

        # Check possible duplicate without disclosing the result to public users.
        applicants = request.env['hr.applicant'].sudo().with_company(config.company_id)
        duplicate_domain = [('company_id', '=', config.company_id.id),
                            ('flexsys_career_is_general', '=', True)]
        if email:
            duplicate_domain += ['|', ('partner_phone', '=', phone), ('email_from', '=', email)]
        else:
            duplicate_domain += [('partner_phone', '=', phone)]
        possible_duplicate = bool(applicants.search(duplicate_domain, limit=1))

        # Unique request_key constraint serializes concurrent submissions.
        try:
            with request.env.cr.savepoint():
                record = ledger.create({
                    'request_key': request_key, 'company_id': config.company_id.id,
                    'ip_hash': ip_hash, 'state': 'processing',
                })
        except IntegrityError:
            matching = ledger.search([('request_key', '=', request_key),
                                      ('company_id', '=', config.company_id.id)], limit=1)
            if matching and matching.state == 'completed':
                return request.redirect('/careers/success?ref=%s' % matching.reference, code=303)
            return self._render_error(config, 'Request already submitted.')

        reference = request.env['ir.sequence'].sudo().next_by_code('flexsys.career.reference')
        if not reference:
            raise RuntimeError('Career reference sequence is not configured.')
        vals = {
            'partner_name': name, 'partner_phone': phone, 'email_from': email or False,
            'company_id': config.company_id.id, 'job_id': False,
            'talent_pool_ids': [(4, pool.id)],
            'flexsys_career_is_general': True, 'flexsys_career_reference': reference,
            'flexsys_career_category_id': category.id, 'flexsys_career_city': city,
            'flexsys_career_experience_years': years, 'flexsys_career_education': education,
            'flexsys_career_privacy_version': config.privacy_version,
            'flexsys_career_acknowledged_at': fields.Datetime.now(),
            'flexsys_career_source': 'web',
            'flexsys_career_retention_until': (fields.Date.today() + relativedelta(months=config.retention_months)) if config.retention_months > 0 else False,
            'flexsys_career_duplicate_candidate': possible_duplicate,
        }
        applicant = applicants.with_context(tracking_disable=True, mail_create_nosubscribe=True).create(vals)
        attachment = request.env['ir.attachment'].sudo().with_company(config.company_id).create({
            'name': 'CV-' + reference + '.' + uploaded.filename.rsplit('.', 1)[-1].lower(),
            'datas': base64.b64encode(raw), 'mimetype': mime,
            'res_model': 'hr.applicant', 'res_id': applicant.id, 'public': False,
        })
        applicant.write({'flexsys_career_resume_id': attachment.id})
        if notes:
            applicant.message_post(body='Applicant comments: %s' % escape(notes), message_type='comment', subtype_xmlid='mail.mt_note')
        record.write({'applicant_id': applicant.id, 'reference': reference, 'state': 'completed'})
        if email and config.auto_acknowledgment:
            try:
                with request.env.cr.savepoint():
                    request.env['mail.mail'].sudo().create({
                        'subject': 'Application received — %s' % reference,
                        'email_to': email,
                        'body_html': '<p>We have received your job application. Reference: %s</p>' % escape(reference),
                        'auto_delete': True,
                    })
            except Exception:
                _logger.warning('Could not queue Careers acknowledgement for ref %s', reference)
        return request.redirect('/careers/success?ref=%s' % reference, code=303)
