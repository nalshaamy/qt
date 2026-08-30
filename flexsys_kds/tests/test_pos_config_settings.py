# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestPosConfigSettings(FlexSysKdsTestCommon):
    """UI/DATA FIX ("Master Change Request", Batch 2), items 10 and 11:
    POS Send-to-KDS Settings scope + naming cleanup.

    Deliberately its own file, independent of test_pos_sync.py's own
    heavier pos.session-based fixtures - these tests only need a bare
    pos.config record and this module's own kds.station, not a full
    working POS session/order flow.
    """

    def test_item10_pos_linked_to_station_is_in_scope(self):
        """Required Acceptance: 'أي POS مرتبط بـ POS Configs في Station
        واحدة على الأقل -> يعتبر داخل نطاق FlexSys KDS.'"""
        config = self._make_test_pos_config('Item10 Linked POS')
        self.station_kitchen.pos_config_ids = [(4, config.id)]

        in_scope = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([('id', '=', config.id)])

        self.assertTrue(in_scope, "A POS linked to at least one station must be in scope.")

    def test_item10_pos_not_linked_to_any_station_is_out_of_scope(self):
        """Required Acceptance: 'POS غير مرتبط بأي Station -> لا يظهر
        في القائمة.'"""
        config = self._make_test_pos_config('Item10 Unlinked POS')
        # Explicitly NOT linked to any kds.station.

        in_scope = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([('id', '=', config.id)])

        self.assertFalse(in_scope, "A POS linked to no station at all must not appear.")

    def test_item10_removing_pos_from_all_stations_removes_it_from_scope(self):
        """Required: 'إذا تمت إزالة POS من جميع Stations: يختفي من
        الشاشة.'"""
        config = self._make_test_pos_config('Item10 Removed POS')
        self.station_kitchen.pos_config_ids = [(4, config.id)]
        self.assertTrue(
            self.env['pos.config'].with_context(flexsys_kds_scope_only=True)
            .search([('id', '=', config.id)]))

        self.station_kitchen.pos_config_ids = [(3, config.id)]

        in_scope_after = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([('id', '=', config.id)])
        self.assertFalse(in_scope_after, "Removing the POS from every station must remove "
                                          "it from this screen's own scope.")

    def test_item10_historical_setting_preserved_after_removal_from_scope(self):
        """Required: 'لا يلزم حذف إعداداته التاريخية داخليًا.' Confirms
        kds_send_trigger itself is never touched by entering/leaving
        scope - only this screen's own visibility is affected."""
        config = self._make_test_pos_config('Item10 Preserved Setting')
        self.station_kitchen.pos_config_ids = [(4, config.id)]
        config.kds_send_trigger = 'send'

        self.station_kitchen.pos_config_ids = [(3, config.id)]
        config.invalidate_recordset()
        self.assertEqual(
            config.kds_send_trigger, 'send',
            "The POS's own historical setting must be preserved internally, "
            "completely untouched, even after it leaves scope.")

        # And correctly reappears if linked to a station again later.
        self.station_kitchen.pos_config_ids = [(4, config.id)]
        in_scope_again = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([('id', '=', config.id)])
        self.assertIn(config, in_scope_again)
        self.assertEqual(config.kds_send_trigger, 'send')

    def test_item10_scope_filter_context_does_not_leak_to_other_searches(self):
        """Confirms the flexsys_kds_scope_only context key only ever
        activates this specific filtering when explicitly set - an
        ordinary pos.config search elsewhere in the system (no such
        context key at all) must be completely unaffected, still
        finding a POS not linked to any station."""
        config = self._make_test_pos_config('Item10 Ordinary Search POS')
        # No context override at all - the default, ordinary case every
        # other screen/module relies on.
        found = self.env['pos.config'].search([('id', '=', config.id)])
        self.assertIn(config, found, "Without the special context key, an ordinary search "
                                      "must behave exactly as it always has.")

    def test_item10_kds_station_ids_computed_field_reflects_links(self):
        """Confirms the underlying (unstored, display-only)
        kds_station_ids field itself correctly reflects which stations
        a POS is actually linked to."""
        config = self._make_test_pos_config('Item10 Computed Field POS')
        self.assertFalse(config.kds_station_ids)

        self.station_kitchen.pos_config_ids = [(4, config.id)]
        config.invalidate_recordset()
        self.assertIn(self.station_kitchen, config.kds_station_ids)

    def test_item11_send_trigger_selection_values_unchanged(self):
        """Required: item 11's own 'لا تغيير على المنطق الحالي' -
        confirms the underlying Selection VALUES stored in the database
        ('payment'/'send') are completely unchanged - only their own
        display labels were updated."""
        config = self._make_test_pos_config('Item11 Values POS')
        selection_values = dict(config._fields['kds_send_trigger'].selection)
        self.assertIn('payment', selection_values)
        self.assertIn('send', selection_values)

        config.kds_send_trigger = 'send'
        config.invalidate_recordset()
        self.assertEqual(config.kds_send_trigger, 'send',
                          "The 'send' value itself must still be assignable and readable "
                          "exactly as before - only its own display label changed.")

    def test_item11_field_string_and_labels_updated(self):
        """Confirms the field's own string and the 'send' option's own
        label were genuinely updated to the required text."""
        config = self.env['pos.config']
        self.assertEqual(config._fields['kds_send_trigger'].string, 'Send Order to KDS')
        selection_labels = dict(config._fields['kds_send_trigger'].selection)
        self.assertEqual(selection_labels['send'], 'When Sent from POS')
        self.assertEqual(selection_labels['payment'], 'After Payment')

    # -----------------------------------------------------------------
    # REAL BUG FIX ("Batch 2 live test - Item 10 recursion crash"),
    # confirmed live: opening the Send-to-KDS Settings screen crashed
    # with a RecursionError - the original _search() implementation
    # resolved in-scope ids via `.pos_config_ids.ids` (an ORM Many2many
    # field read) called FROM WITHIN the override itself, which
    # re-entered pos.config._search() through the ORM's own internal
    # field-resolution machinery, still carrying the same context flag
    # - infinite recursion. Fixed with a direct SQL query against the
    # relation table instead, which never touches the ORM's own
    # pos.config field-read path at all. These tests actually execute
    # search()/_search()/web_search_read() end to end with the real
    # scope context, as explicitly required, rather than only testing
    # the resulting domain/ids in isolation.
    # -----------------------------------------------------------------
    def test_item10_search_with_scope_context_does_not_recurse(self):
        """Required regression test: actually executes search() (which
        calls the real, overridden _search() internally) with the KDS
        scope context and confirms it completes normally - no
        RecursionError, whether or not any station/POS links exist at
        all in this test's own database state."""
        try:
            result = self.env['pos.config'].with_context(
                flexsys_kds_scope_only=True).search([])
        except RecursionError:
            self.fail("pos.config.search() with flexsys_kds_scope_only=True must never "
                      "recurse - confirmed live crash this test guards against.")
        # Whatever the actual scoped result is, it must be a real,
        # usable recordset - confirms the method returned normally,
        # not just that no exception happened to propagate yet.
        self.assertEqual(result._name, 'pos.config')

    def test_item10_search_with_scope_context_returns_correct_ids(self):
        """The same real search() call as above, this time confirming
        it also returns the CORRECT scoped result - both the recursion
        fix and the original scoping requirement verified together in
        one real end-to-end call."""
        in_scope_config = self._make_test_pos_config('Item10 Regression In Scope')
        out_of_scope_config = self._make_test_pos_config('Item10 Regression Out of Scope')
        self.station_kitchen.pos_config_ids = [(4, in_scope_config.id)]

        result = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([
                ('id', 'in', [in_scope_config.id, out_of_scope_config.id])])

        self.assertIn(in_scope_config, result)
        self.assertNotIn(out_of_scope_config, result)

    def test_item10_web_search_read_with_scope_context_does_not_recurse(self):
        """Required regression test: exercises web_search_read()
        specifically - the actual RPC method the real Send-to-KDS
        Settings list view calls when it opens in the browser - with
        the real scope context, confirming no recursion through that
        exact call path either, not just the lower-level search().

        The exact keyword-argument shape of web_search_read() has
        genuinely changed across Odoo versions (fields vs. specification)
        - this test is deliberately tolerant of that (an unexpected
        signature is not what this test exists to catch, and results in
        a skip rather than a failure, so it doesn't mask the one thing
        that actually matters here); a RecursionError specifically is
        the one failure this test must catch, since that is the exact
        confirmed live bug being guarded against, and it's checked
        around EVERY attempted call shape, not just the first."""
        in_scope_config = self._make_test_pos_config('Item10 WSR In Scope')
        self.station_kitchen.pos_config_ids = [(4, in_scope_config.id)]
        scoped_model = self.env['pos.config'].with_context(flexsys_kds_scope_only=True)

        result = None
        last_type_error = None
        for call in (
            lambda: scoped_model.web_search_read(domain=[], specification={'name': {}}),
            lambda: scoped_model.web_search_read([], ['name']),
        ):
            try:
                result = call()
                break
            except RecursionError:
                self.fail("web_search_read() with flexsys_kds_scope_only=True must never "
                          "recurse - this is the exact call path the real screen uses.")
            except TypeError as e:
                last_type_error = e
                continue

        if result is None:
            self.skipTest(
                "web_search_read()'s own keyword signature differs from both forms "
                "tried in this Odoo version (%r) - not what this regression test exists "
                "to verify; see test_item10_search_with_scope_context_does_not_recurse "
                "for the version-stable equivalent check." % (last_type_error,))
        self.assertIn('records', result)

    def test_item10_sql_relation_lookup_matches_orm_field_value(self):
        """Confirms the direct-SQL relation-table lookup used inside
        _search() produces results identical to what the ORM's own
        (safe, outside-the-override) field read returns - the fix
        changed HOW the in-scope ids are resolved, never WHAT they
        resolve to."""
        config_a = self._make_test_pos_config('Item10 SQL Match A')
        config_b = self._make_test_pos_config('Item10 SQL Match B')
        self.station_kitchen.pos_config_ids = [(4, config_a.id), (4, config_b.id)]

        field = self.env['kds.station']._fields['pos_config_ids']
        self.env.cr.execute(
            'SELECT DISTINCT "%s" FROM "%s"' % (field.column2, field.relation))
        sql_ids = {row[0] for row in self.env.cr.fetchall()}

        # Read via the ORM directly here, OUTSIDE of pos.config's own
        # _search() override (this test itself never sets the scope
        # context), so this read is safe and recursion-free - it's the
        # correctness baseline the SQL query is compared against.
        orm_ids = set(self.station_kitchen.pos_config_ids.ids)

        self.assertTrue({config_a.id, config_b.id}.issubset(sql_ids))
        self.assertEqual(sql_ids & {config_a.id, config_b.id}, orm_ids & {config_a.id, config_b.id})
