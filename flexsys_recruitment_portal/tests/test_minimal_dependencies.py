"""Standalone regression tests: direct dependencies only, no live Odoo needed."""
import ast
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class TestDirectDependencies(unittest.TestCase):
    def test_manifest_minimal_dependencies(self):
        manifest = ast.literal_eval((ROOT / '__manifest__.py').read_text(encoding='utf-8'))
        self.assertEqual(manifest['depends'], ['hr_recruitment'])
        self.assertEqual(manifest['version'], '19.0.1.0.4')
        self.assertTrue(all((ROOT / p).is_file() for p in manifest['data']))
    def test_frontend_is_standalone(self):
        xml = (ROOT / 'views/career_templates.xml').read_text(encoding='utf-8')
        ctl = (ROOT / 'controllers/careers.py').read_text(encoding='utf-8')
        self.assertNotIn('t-call-assets', xml)
        self.assertNotIn('website.layout', xml)
        self.assertNotIn('web.frontend_layout', xml)
        self.assertNotIn('request.website', ctl.replace('No `website` model or `request.website` is required.', ''))
        self.assertNotIn('website=True', ctl)
        self.assertIn('href="/flexsys_recruitment_portal/static/src/css/careers.css?v=19.0.1.0.4"', xml)
        self.assertIn("auth='public'", ctl)
    def test_no_imports_odoo_web_addon(self):
        import ast
        for file in [*(ROOT/'models').glob('*.py'), *(ROOT/'controllers').glob('*.py'), *(ROOT/'services').glob('*.py')]:
            tree = ast.parse(file.read_text(encoding='utf-8'))
            for item in ast.walk(tree):
                if isinstance(item, ast.ImportFrom) and item.module:
                    self.assertFalse(item.module.startswith('odoo.addons.web'), file.name)
                if isinstance(item, ast.Import):
                    self.assertFalse(any(n.name.startswith('odoo.addons.web') for n in item.names), file.name)
if __name__ == '__main__':
    unittest.main()
