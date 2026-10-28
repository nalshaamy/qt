"""Static regression checks runnable with pytest, no live Odoo required."""
from pathlib import Path
import ast
import unittest
from lxml import etree
import tinycss2

ROOT = Path(__file__).resolve().parents[1]

class TestStandaloneAssets(unittest.TestCase):
    def test_no_scss_in_manifest(self):
        m = ast.literal_eval((ROOT/'__manifest__.py').read_text())
        self.assertNotIn('assets', m)
        self.assertNotIn('website', m['depends'])
        self.assertNotIn('web', m['depends'])
        self.assertEqual(m['depends'], ['hr_recruitment'])
    def test_no_asset_compilation_call_in_qweb(self):
        content = (ROOT/'views/career_templates.xml').read_text()
        self.assertNotIn('t-call-assets',content)
        self.assertEqual(content.count('/static/src/css/careers.css?v=19.0.1.0.4'),2)
        self.assertIn('width="52" height="52"',content)
        etree.fromstring(content.encode())
    def test_css_flat_and_valid_tokens(self):
        rules = tinycss2.parse_stylesheet((ROOT/'static/src/css/careers.css').read_text(), skip_comments=True,skip_whitespace=True)
        self.assertTrue(rules)
        self.assertFalse(any(rule.type=='error' for rule in rules))
        for r in rules:
            self.assertIn(r.type,('qualified-rule','at-rule'))
            if r.type=='qualified-rule':
                self.assertTrue(tinycss2.serialize(r.prelude).strip().startswith('.fs-careers'))
                inside=tinycss2.parse_declaration_list(r.content,skip_comments=True,skip_whitespace=True)
                self.assertTrue(all(t.type=='declaration' for t in inside))
            else:
                self.assertEqual(r.lower_at_keyword,'media')
                inside=tinycss2.parse_rule_list(r.content,skip_comments=True,skip_whitespace=True)
                self.assertTrue(all(t.type=='qualified-rule' for t in inside))
    def test_assets_exist(self):
        self.assertTrue((ROOT/'static/src/css/careers.css').is_file())
        self.assertTrue((ROOT/'static/src/js/careers.js').is_file())
        self.assertFalse((ROOT/'static/src/scss/careers.scss').exists())

if __name__=='__main__':
    unittest.main()
