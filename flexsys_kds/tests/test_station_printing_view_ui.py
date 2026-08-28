# -*- coding: utf-8 -*-
"""Commercial Demo UI - Station Printing Configuration Cleanup
regression suite.

Reads views/kds_station_views.xml's own real source text directly
(no live browser/Odoo runtime available in this environment to render
and inspect the actual rendered form) - the same "read the real file
directly" approach already used for kds_style.scss/kds_kiosk.py in
tests/test_pagination.py. These confirm the SOURCE TEXT itself has the
required structure, not that a browser actually renders it correctly -
a live Odoo.sh visual check remains the real confirmation of that.
"""
import os
import re

from odoo.tests import TransactionCase, tagged


def _read_station_view():
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(module_dir, 'views', 'kds_station_views.xml')
    with open(path, encoding='utf-8') as f:
        return f.read()


@tagged('post_install', '-at_install')
class TestStationPrintingViewUI(TransactionCase):
    """No database fixtures needed - pure XML-source-text
    verification."""

    def test_no_separate_adjacent_printers_tab_remains(self):
        """The specific customer-facing confusion this round fixes:
        two similarly-named tabs ("Printing" and "Printers") with no
        clear reason printing config was split across them. Only ONE
        page with string="Printing" must exist now, and no separately-
        labeled "Printers" page at all."""
        content = _read_station_view()
        printing_pages = re.findall(r'<page\s+name="flexsys_printing"\s+string="Printing"', content)
        self.assertEqual(len(printing_pages), 1, "Exactly one merged 'Printing' page must exist.")
        self.assertNotRegex(
            content, r'<page[^>]*\bstring="Printers"',
            "No separate, adjacent 'Printers' tab may remain - it must be merged "
            "into the single 'Printing' tab."
        )

    def _get_printing_page_body(self):
        content = _read_station_view()
        match = re.search(
            r'<page\s+name="flexsys_printing"\s+string="Printing"[^>]*>(.*?)</page>',
            content, re.DOTALL
        )
        self.assertIsNotNone(match, "Merged 'Printing' page not found at all.")
        return match.group(0), match.group(1)

    def test_printing_configuration_still_available(self):
        _, body = self._get_printing_page_body()
        self.assertIn('flexsys_printing_method', body)
        self.assertIn('widget="radio"', body)

    def test_direct_network_fields_still_conditional(self):
        """Direct Network's own two fields must still exist and still
        be shown/hidden by the same flexsys_printing_method condition
        as before the merge - now applied once, at the group level,
        rather than duplicated on each field individually (a
        simplification with the exact same resulting visibility, not
        a behavior change)."""
        _, body = self._get_printing_page_body()
        self.assertIn('flexsys_printer_ip', body)
        self.assertIn('flexsys_use_local_network_access', body)
        self.assertIn("invisible=\"flexsys_printing_method != 'direct_network'\"", body)

    def test_legacy_printer_management_still_accessible(self):
        """Confirms printer_ids (the kds.printer/Legacy Agent
        management list - name, type, IP, default/backup flags,
        status) is still present and fully editable within the merged
        tab - no functionality removed, only relocated from its own
        former separate tab into a labeled section of this one."""
        _, body = self._get_printing_page_body()
        self.assertIn('field name="printer_ids"', body)
        for expected_field in ('name', 'printer_type', 'ip_address', 'is_default', 'is_backup', 'status'):
            self.assertIn('field name="%s"' % expected_field, body)
        self.assertIn('editable="bottom"', body)

    def test_operating_mode_visibility_unchanged(self):
        """The merged page must still carry the exact same
        invisible= condition BOTH prior separate tabs shared
        (invisible when operating_mode == 'kds_only') - Operating Mode
        logic itself is completely untouched by this round; this only
        confirms the single merged tab didn't accidentally drop or
        alter that condition during the merge."""
        full_tag, _ = self._get_printing_page_body()
        self.assertIn("invisible=\"operating_mode == 'kds_only'\"", full_tag)

    def test_printing_tab_organized_into_three_labeled_sections(self):
        """Confirms the three requested visual sections (A. Printing
        Method, B. Direct Network Settings, C. Print Agent / Printer
        Management) are genuinely present as distinct, labeled
        groups/separators - not just all three areas of content
        dumped together with no structure."""
        _, body = self._get_printing_page_body()
        self.assertIn('string="Printing Method"', body)
        self.assertIn('string="Direct Network Settings"', body)
        self.assertIn('string="Print Agent / Printer Management"', body)

    def test_iot_is_not_selectable_in_station_printing_ui(self):
        """FINAL MINOR CLOSEOUT ("Station Printing Cleanup"): confirmed
        live - the prior round's own fix only relabeled the option's
        own text to "Not Available Yet" while leaving it just as
        selectable as any other radio button, which is not an actual
        fix - a customer could still click it and end up with a
        non-working print path. This test proves IoT is genuinely NOT
        offered as a choice any more (not merely that its label says
        so), while confirming the underlying 'iot' field value itself
        is still fully preserved for backward compatibility with any
        already-existing station record.
        """
        model_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'models', 'kds_station.py'
        )
        with open(model_path, encoding='utf-8') as f:
            model_content = f.read()

        # The field must use a DYNAMIC selection (a method name string),
        # not a static Python list literally containing both options
        # together and unconditionally - a static list is exactly what
        # made 'iot' just as selectable as 'direct_network' before,
        # regardless of what text label was on it.
        field_match = re.search(
            r"flexsys_printing_method\s*=\s*fields\.Selection\(\s*\n\s*selection='([^']+)'",
            model_content
        )
        self.assertIsNotNone(
            field_match,
            "flexsys_printing_method must use a dynamic selection=<method name> callable, "
            "not a static inline list - a static list cannot conditionally exclude an option."
        )
        method_name = field_match.group(1)

        # Extract that method's own body and confirm its structure
        # directly: 'iot' must appear ONLY inside a conditional guard,
        # never as an unconditional entry in the base/default list the
        # method starts with.
        method_match = re.search(
            r'def %s\(self\)(.*?)(?=\n    def |\n    [a-zA-Z_]+\s*=\s*fields\.|\Z)' % re.escape(method_name),
            model_content, re.DOTALL
        )
        self.assertIsNotNone(method_match, "%s() method not found." % method_name)
        method_body = method_match.group(1)

        base_list_match = re.search(r'options\s*=\s*\[(.*?)\]', method_body)
        self.assertIsNotNone(base_list_match, "Could not find the method's own base options list.")
        base_list = base_list_match.group(1)
        self.assertIn('direct_network', base_list)
        self.assertNotIn(
            "'iot'", base_list,
            "'iot' must NOT be in the unconditional base options list - it must only ever "
            "be appended inside a conditional guard, never offered unconditionally."
        )

        # 'iot' must appear elsewhere in the method, but gated behind a
        # condition checking the record's own CURRENT stored value -
        # this is what keeps a pre-existing 'iot' station's own value
        # displaying correctly without offering it as a new choice to
        # anyone else.
        self.assertRegex(
            method_body, r"if\s+self\s+and\s+self\.flexsys_printing_method\s*==\s*'iot'",
            "'iot' must only ever be offered back when the record being edited already "
            "has that exact value stored - never unconditionally."
        )
        self.assertIn("options.append(('iot'", method_body)

        # The underlying field value itself must remain fully intact
        # for backward compatibility - this is a selection-availability
        # fix, not a data/schema change.
        self.assertIn("'iot'", model_content)
