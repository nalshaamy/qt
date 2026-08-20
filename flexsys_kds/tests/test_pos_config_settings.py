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
        config = self.env['pos.config'].create({'name': 'Item10 Linked POS'})
        self.station_kitchen.pos_config_ids = [(4, config.id)]

        in_scope = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([('id', '=', config.id)])

        self.assertTrue(in_scope, "A POS linked to at least one station must be in scope.")

    def test_item10_pos_not_linked_to_any_station_is_out_of_scope(self):
        """Required Acceptance: 'POS غير مرتبط بأي Station -> لا يظهر
        في القائمة.'"""
        config = self.env['pos.config'].create({'name': 'Item10 Unlinked POS'})
        # Explicitly NOT linked to any kds.station.

        in_scope = self.env['pos.config'].with_context(
            flexsys_kds_scope_only=True).search([('id', '=', config.id)])

        self.assertFalse(in_scope, "A POS linked to no station at all must not appear.")

    def test_item10_removing_pos_from_all_stations_removes_it_from_scope(self):
        """Required: 'إذا تمت إزالة POS من جميع Stations: يختفي من
        الشاشة.'"""
        config = self.env['pos.config'].create({'name': 'Item10 Removed POS'})
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
        config = self.env['pos.config'].create({'name': 'Item10 Preserved Setting'})
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
        config = self.env['pos.config'].create({'name': 'Item10 Ordinary Search POS'})
        # No context override at all - the default, ordinary case every
        # other screen/module relies on.
        found = self.env['pos.config'].search([('id', '=', config.id)])
        self.assertIn(config, found, "Without the special context key, an ordinary search "
                                      "must behave exactly as it always has.")

    def test_item10_kds_station_ids_computed_field_reflects_links(self):
        """Confirms the underlying (unstored, display-only)
        kds_station_ids field itself correctly reflects which stations
        a POS is actually linked to."""
        config = self.env['pos.config'].create({'name': 'Item10 Computed Field POS'})
        self.assertFalse(config.kds_station_ids)

        self.station_kitchen.pos_config_ids = [(4, config.id)]
        config.invalidate_recordset()
        self.assertIn(self.station_kitchen, config.kds_station_ids)

    def test_item11_send_trigger_selection_values_unchanged(self):
        """Required: item 11's own 'لا تغيير على المنطق الحالي' -
        confirms the underlying Selection VALUES stored in the database
        ('payment'/'send') are completely unchanged - only their own
        display labels were updated."""
        config = self.env['pos.config'].create({'name': 'Item11 Values POS'})
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
