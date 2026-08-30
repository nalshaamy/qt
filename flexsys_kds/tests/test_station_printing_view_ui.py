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

    def test_legacy_printer_management_hidden_from_station_form(self):
        """COMMERCIAL UI CLEANUP ("Hide Legacy Print Agent From
        Commercial UI"), item 2: SUPERSEDES this test's own prior
        version, which protected the OLD behavior of printer_ids being
        directly embedded in this tab - that embedding is now
        deliberately removed from the normal commercial Station form,
        confirmed live. printer_ids itself (and every kds.printer
        record) is completely untouched at the model/data level - only
        no longer shown HERE. Still fully accessible via the
        standalone kds.printer form/list for backward-compatibility/
        admin maintenance (see test_kds_printer_model_and_data_still_exist
        below)."""
        _, body = self._get_printing_page_body()
        self.assertNotIn('field name="printer_ids"', body)
        self.assertNotRegex(body, r'string="Print Agent[^"]*"')
        for legacy_field in ('is_default', 'is_backup', 'printer_type'):
            self.assertNotIn('field name="%s"' % legacy_field, body)

    def test_operating_mode_visibility_unchanged(self):
        """The merged page must still carry the exact same
        invisible= condition BOTH prior separate tabs shared
        (invisible when operating_mode == 'kds_only') - Operating Mode
        logic itself is completely untouched by this round; this only
        confirms the single merged tab didn't accidentally drop or
        alter that condition during the merge."""
        full_tag, _ = self._get_printing_page_body()
        self.assertIn("invisible=\"operating_mode == 'kds_only'\"", full_tag)

    def test_printing_tab_organized_into_two_labeled_sections(self):
        """COMMERCIAL UI CLEANUP: SUPERSEDES this test's own prior
        version, which required a third "Print Agent / Printer
        Management" section - that section is now deliberately hidden
        from this tab (see test_legacy_printer_management_hidden_from_station_form
        above). Only the two currently-supported-commercially sections
        remain."""
        _, body = self._get_printing_page_body()
        self.assertIn('string="Printing Method"', body)
        self.assertIn('string="Direct Network Settings"', body)
        self.assertNotIn('string="Print Agent / Printer Management"', body)

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

    # -----------------------------------------------------------------
    # UI CLEANUP ("Station Form Final Cleanup"), item 1: Description
    # moved from a standalone group above the notebook into its own
    # last tab, "Notes".
    # -----------------------------------------------------------------

    def test_description_no_longer_shown_above_the_notebook(self):
        """Confirmed live: the old standalone 'Description' group sat
        directly above <notebook>, reserving a large, mostly-empty
        block of vertical space at the top of the form on every
        station regardless of whether the field was ever used. Must
        no longer exist there - only what's inside the new 'Notes' tab
        may reference the field now."""
        content = _read_station_view()
        # Everything before the opening <notebook> tag is "above the
        # tabs" - description must not appear there.
        above_notebook = content.split('<notebook>', 1)[0]
        self.assertNotIn('field name="description"', above_notebook)
        self.assertNotRegex(above_notebook, r'<group\s+string="Description"')

    def test_single_notes_tab_exists(self):
        content = _read_station_view()
        notes_pages = re.findall(r'<page\s+name="flexsys_notes"\s+string="Notes"', content)
        self.assertEqual(len(notes_pages), 1, "Exactly one 'Notes' tab must exist.")

    def test_description_field_is_inside_the_notes_tab(self):
        content = _read_station_view()
        match = re.search(
            r'<page\s+name="flexsys_notes"\s+string="Notes"[^>]*>(.*?)</page>',
            content, re.DOTALL
        )
        self.assertIsNotNone(match, "'Notes' tab not found at all.")
        self.assertIn('field name="description"', match.group(1))

    def test_notes_tab_is_translated_to_arabic(self):
        """The client explicitly requested a specific Arabic label
        ("ملاحظات") for this tab - confirms the translation entry
        actually exists in i18n/ar.po, not just that the English tab
        itself exists."""
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        po_path = os.path.join(module_dir, 'i18n', 'ar.po')
        with open(po_path, encoding='utf-8') as f:
            po_content = f.read()
        self.assertRegex(
            po_content,
            r'msgid "Notes"\s*\nmsgstr "ملاحظات"',
            "i18n/ar.po must translate the 'Notes' tab label to 'ملاحظات'."
        )

    # -----------------------------------------------------------------
    # UI CLEANUP ("Station Form Final Cleanup"), item 2: the top
    # "Printers" smart button removed - printer management remains
    # available solely through the Printing tab's own embedded list.
    # -----------------------------------------------------------------

    def test_no_printers_smart_button_on_station_form(self):
        """Confirmed live: after Printing/Printers were merged into
        one tab, this smart button (a shortcut to the same records
        already directly visible/editable inside that tab) duplicated
        the same functionality and reintroduced the exact confusion
        the merge itself was meant to resolve."""
        content = _read_station_view()
        self.assertNotIn('name="action_view_printers"', content)
        self.assertNotRegex(content, r'widget="statinfo"\s+string="Printers"')

    def test_action_view_printers_method_itself_still_exists(self):
        """Explicit requirement: only the ONE visible entry point on
        the Station form is removed - the underlying action/method on
        the model itself must remain untouched and callable from
        anywhere else it might be used."""
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(module_dir, 'models', 'kds_station.py')
        with open(model_path, encoding='utf-8') as f:
            model_content = f.read()
        self.assertIn('def action_view_printers(self)', model_content)
        self.assertIn("printer_count = fields.Integer(", model_content)

    # -----------------------------------------------------------------
    # COMMERCIAL UI CLEANUP ("Hide Legacy Print Agent From Commercial
    # UI"), items 1 and 5 (test list points 1, 2, 5, 6, 8).
    # -----------------------------------------------------------------

    @staticmethod
    def _read_module_file(*relative_parts):
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(module_dir, *relative_parts)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_printing_landing_page_no_longer_shows_printers_card(self):
        """Item 1: confirmed live - the "Printers" card on the
        commercial Printing landing page is removed (replaced by a
        "Station Printing Settings" card linking to Stations, where
        Direct Network is actually configured now)."""
        content = self._read_module_file('views', 'kds_printer_hub_views.xml')
        self.assertNotIn('<h5 class="card-title">Printers</h5>', content)
        self.assertNotIn('action_kds_printer)d', content)
        # The replacement card must genuinely exist, not just have the
        # old one silently deleted with nothing put in its place.
        self.assertIn('Station Printing Settings', content)
        self.assertIn('action_kds_station)d', content)

    def test_print_jobs_card_remains_on_landing_page(self):
        """Item 1 (and 4): Print Jobs is explicitly required to
        remain - it's the primary operational card for BOTH
        transports now."""
        content = self._read_module_file('views', 'kds_printer_hub_views.xml')
        self.assertIn('<h5 class="card-title">Print Jobs</h5>', content)
        self.assertIn('action_kds_print_job)d', content)

    def test_kds_printer_model_and_action_still_exist(self):
        """Item 5/6: the kds.printer MODEL itself, its own action, and
        every existing printer record's own underlying storage remain
        completely untouched - this round only hides UI entry points,
        never deletes model/data/backend functionality."""
        model_content = self._read_module_file('models', 'kds_printer.py')
        self.assertIn("_name = 'kds.printer'", model_content)

        hub_or_printer_views = self._read_module_file('views', 'kds_printer_views.xml')
        self.assertIn('<record id="action_kds_printer"', hub_or_printer_views)

    def test_agent_backend_routes_and_logic_not_removed(self):
        """Item 6: confirmed by direct read - the Legacy Agent's own
        claim/dispatch/retry/fallback logic in kds_print_job.py, and
        create_reprint()'s own station.printer_ids requirement, are
        both still fully present - this is a UI-hiding round only, per
        explicit "Do NOT delete or disable yet" direction."""
        model_content = self._read_module_file('models', 'kds_print_job.py')
        self.assertIn('def create_reprint(self', model_content)
        self.assertIn('def action_mark_failed(self', model_content)
        self.assertIn('_claim_pending_jobs', model_content)
        self.assertIn('MAX_AUTO_RETRY', model_content)

    def test_auto_print_runtime_source_untouched(self):
        """Item 8: confirms this round touched no Auto Print/Printer
        Only runtime logic at all - only the three view files (Station
        form, Printing landing page, Print Job list) and the
        kds.printer form's own banner text were modified. A crude but
        honest static guard: the action_print_full_order() method
        (Auto Print's own entry point) must still exist unchanged in
        the model layer, which this round never touched."""
        model_content = self._read_module_file('models', 'kds_order.py')
        self.assertIn('def action_print_full_order(self', model_content)

    def test_print_agent_only_printer_specific_banner(self):
        """Item 3: confirms the obsolete "this module does not talk to
        a physical printer directly" claim (no longer true now that
        Direct Network exists) is gone from the kds.printer form, and
        replaced with wording scoped correctly to what this form
        itself actually is - a Legacy Agent printer record, not a
        statement about the product's printing architecture as a
        whole."""
        content = self._read_module_file('views', 'kds_printer_views.xml')
        self.assertNotIn('it does not talk to a physical printer', content)
        self.assertIn('Legacy Print Agent printer specifically', content)
        self.assertIn('Direct Network', content)

    def test_printing_landing_subtitle_no_longer_leads_with_printers(self):
        """COMMERCIAL AGENT UI CLEANUP ("Final Visible Text Closeout"),
        item 1: confirmed live - "Printers and print job history."
        still named "Printers" as the landing page's own subtitle,
        contradicting the earlier removal of the Printers card itself.
        Replaced with wording describing what the two current cards
        actually are."""
        content = self._read_module_file('views', 'kds_printer_hub_views.xml')
        self.assertNotIn('Printers and print job history.', content)
        self.assertIn('Direct Network settings and print job history.', content)

    def test_new_landing_page_strings_have_arabic_translations(self):
        """Item 2: the three newly-introduced visible strings on the
        landing page (the "Station Printing Settings" card's own
        title, description, and button label) plus the updated
        subtitle must all have real, non-empty Arabic translations in
        i18n/ar.po - not just exist in the English source. Uses a
        proper multiline-aware .po parser (matching the one used
        throughout this module's own localization test suite) since
        gettext wraps longer strings across multiple quoted lines that
        a plain substring search would miss."""
        import re as _re

        def _parse_po_entries(content):
            entries = []
            cur_id, cur_str, mode = None, None, None

            def _unescape(s):
                return s.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')

            for raw_line in content.splitlines():
                line = raw_line.strip()
                if line.startswith('msgid '):
                    if cur_id is not None:
                        entries.append((''.join(cur_id), ''.join(cur_str or [])))
                    cur_id, cur_str, mode = [], None, 'msgid'
                    m = _re.match(r'msgid\s+"(.*)"$', line)
                    if m:
                        cur_id.append(m.group(1))
                elif line.startswith('msgstr '):
                    cur_str, mode = [], 'msgstr'
                    m = _re.match(r'msgstr\s+"(.*)"$', line)
                    if m:
                        cur_str.append(m.group(1))
                elif line.startswith('"') and line.endswith('"') and mode:
                    c = line[1:-1]
                    (cur_id if mode == 'msgid' else cur_str).append(c)
                elif not line:
                    mode = None
            if cur_id is not None:
                entries.append((''.join(cur_id), ''.join(cur_str or [])))
            return {_unescape(mid): _unescape(mstr) for mid, mstr in entries}

        view_content = self._read_module_file('views', 'kds_printer_hub_views.xml')
        po_content = self._read_module_file('i18n', 'ar.po')
        translations = _parse_po_entries(po_content)

        required_strings = [
            "Direct Network settings and print job history.",
            "Station Printing Settings",
            "Open Stations",
            "Configure Direct Network printing (Epson ePOS) per station - "
            "Printer IP and Local Network Access, under each station's own Printing tab.",
        ]
        for text in required_strings:
            self.assertIn(text, view_content, "%r not found in the live view at all." % text)
            self.assertIn(text, translations, "%r has no ar.po entry at all." % text)
            self.assertTrue(translations[text], "%r has an empty Arabic translation." % text)

        # The old, now-removed subtitle's own translation entry must
        # not remain as stale, orphaned data pointing at English text
        # that no longer exists anywhere in the module.
        self.assertNotIn("Printers and print job history.", translations)
