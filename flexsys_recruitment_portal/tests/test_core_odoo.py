"""Server integration cases to execute in Odoo.sh with --test-enable.

Tests are NOT run by local offline pytest because the Odoo server is unavailable.
"""
import base64
from io import BytesIO
from PIL import Image

from odoo.tests import TransactionCase, HttpCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestFlexSysRecruitmentIntegration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.config = cls.env['flexsys.career.config'].sudo().search([('company_id', '=', cls.company.id)], limit=1)

    def test_initial_company_setup(self):
        self.assertTrue(self.config)
        self.assertEqual(self.config.company_id, self.company)
        self.assertTrue(self.config.default_talent_pool_id)
        self.assertEqual(
            int(self.env['ir.config_parameter'].sudo().get_param(
                'flexsys_recruitment_portal.public_config_id')), self.config.id)

    def test_general_applicant_without_job(self):
        app = self.env['hr.applicant'].create({
            'partner_name': 'Test Person', 'company_id': self.company.id,
            'job_id': False, 'flexsys_career_is_general': True,
            'talent_pool_ids': [(4, self.config.default_talent_pool_id.id)],
            'flexsys_career_reference': 'CR-2099-123456',
        })
        self.assertFalse(app.job_id)
        self.assertTrue(app.is_pool_applicant)
        self.assertEqual(app.pool_applicant_id, app)

    def test_unique_submission_token(self):
        Ledger = self.env['flexsys.career.submission'].sudo()
        vals = {'request_key':'00000000-0000-4000-8000-123456789abc',
                'company_id':self.company.id}
        Ledger.create(vals)
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                Ledger.create(vals)

    def test_cross_company_config_guard(self):
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['flexsys.career.config'].sudo().create({
                    'company_id': self.company.id,
                })

    def test_brand_publish_revision(self):
        image = Image.new('RGB', (80,80), '#257baa')
        buf = BytesIO(); image.save(buf, format='PNG')
        self.config.brand_logo_candidate = base64.b64encode(buf.getvalue())
        before = self.config.brand_revision
        self.config.action_preview_brand()
        self.assertTrue(self.config.brand_draft_palette)
        self.config.action_publish_brand()
        self.assertEqual(self.config.brand_revision, before + 1)
        self.assertTrue(self.config.brand_palette_json)

    def test_cross_company_talent_pool_rejected(self):
        other = self.env['res.company'].create({'name': 'Example Isolation Test Company'})
        other_pool = self.env['hr.talent.pool'].sudo().create({
            'name': 'Other pool', 'company_id': other.id,
        })
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.env['hr.applicant'].sudo().create({
                    'partner_name': 'Cross Company Candidate',
                    'company_id': self.company.id,
                    'flexsys_career_is_general': True,
                    'talent_pool_ids': [(4, other_pool.id)],
                })

    def test_public_user_no_applicant_read(self):
        public = self.env.ref('base.public_user')
        self.assertFalse(self.env['hr.applicant'].with_user(public).has_access('read'))
        self.assertFalse(self.env['ir.attachment'].with_user(public).has_access('create'))


@tagged('post_install', '-at_install')
class TestPublicRoutesWithoutWebsite(HttpCase):
    """Run against a real Odoo test database, ideally *without* website addon."""

    def test_public_careers_home(self):
        result = self.url_open('/careers')
        self.assertEqual(result.status_code, 200)
        self.assertIn('Careers', result.text)

    def test_public_application_form(self):
        result = self.url_open('/careers/apply')
        self.assertEqual(result.status_code, 200)
        self.assertIn('csrf_token', result.text)
        self.assertIn('multipart/form-data', result.text)

    def test_public_privacy(self):
        result = self.url_open('/careers/privacy')
        self.assertEqual(result.status_code, 200)
        self.assertIn('privacy', result.text.lower())
