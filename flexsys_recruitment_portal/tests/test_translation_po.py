"""Regression guard: the shipped PO entries must be readable by Odoo 19.
Run through Odoo's test runner as part of Staging checks.
"""
import re
from pathlib import Path
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestArabicPoMetadata(TransactionCase):
    def test_each_translation_has_required_module_comment(self):
        path = Path(__file__).parents[1] / 'i18n' / 'ar.po'
        contents = path.read_text(encoding='utf-8')
        entries = [e for e in contents.split('\n\n') if 'msgid "' in e and 'msgid ""' not in e]
        self.assertGreater(len(entries), 0)
        for entry in entries:
            match = re.search(r'^#\. (module[s]?: .+)$', entry, re.M)
            self.assertIsNotNone(match, entry[:100])
            self.assertIsNotNone(re.match(r'(module[s]?): (\w+)', match.group(1)))
