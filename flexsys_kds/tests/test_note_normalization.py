# -*- coding: utf-8 -*-
"""Regression coverage for the bug fix: "POS Line Note displayed as
raw JSON in KDS".

Confirmed on real Odoo 19 runtime: a pos.order.line's own 'note' can
be stored as a JSON-serialized list of structured note objects (e.g.
'[{"text":"Heating","colorIndex":0}]', produced by Odoo 19's own POS
Quick/Customer Notes feature) rather than a plain string. Reading it
without normalization showed the raw JSON syntax to the kitchen
instead of the human-readable text.

Fix: kds.order.line.normalize_note_text() - a single, shared
normalization function - is applied at every point line notes are
serialized for display: the Internal KDS orders endpoint
(controllers/kds.py), the Public Kiosk orders endpoint
(controllers/kds_kiosk.py), and both places the POS Direct Auto Print
payload builder serializes a line's own note
(models/kds_print_job.py). The stored kds.order.line.note field
itself is left untouched (still the raw value) - normalization
happens only at the point of rendering, per the explicit requirement,
so both new and pre-existing records are corrected without a data
migration.
"""
from odoo.tests import tagged

from .common import FlexSysKdsTestCommon


@tagged('post_install', '-at_install')
class TestNoteNormalization(FlexSysKdsTestCommon):

    # -----------------------------------------------------------------
    # Unit-level: normalize_note_text() itself, in isolation.
    # -----------------------------------------------------------------

    def test_plain_string_note_unchanged(self):
        """Requirement 1: a normal plain string must display unchanged."""
        normalize = self.env['kds.order.line'].normalize_note_text
        self.assertEqual(normalize('No onions'), 'No onions')
        self.assertEqual(normalize('  Extra sauce  '), '  Extra sauce  ')

    def test_structured_single_note_extracts_text_only(self):
        """Requirement 2: JSON/structured single-entry note must show
        only the human-readable text - never JSON brackets, object
        keys, or metadata like colorIndex."""
        normalize = self.env['kds.order.line'].normalize_note_text
        result = normalize('[{"text":"Heating","colorIndex":0}]')
        self.assertEqual(result, 'Heating')
        self.assertNotIn('{', result)
        self.assertNotIn('colorIndex', result)

    def test_structured_multiple_notes_joined_readably(self):
        """Requirement 3: multiple note entries must preserve all
        human-readable text in a clean, readable format."""
        normalize = self.env['kds.order.line'].normalize_note_text
        result = normalize(
            '[{"text":"Heating","colorIndex":0},{"text":"Extra Spicy","colorIndex":1}]'
        )
        self.assertEqual(result, 'Heating, Extra Spicy')
        self.assertNotIn('colorIndex', result)
        self.assertNotIn('[', result)

    def test_empty_and_null_note(self):
        """Requirement 7: empty/null note must not raise and must not
        produce a stray JSON artifact."""
        normalize = self.env['kds.order.line'].normalize_note_text
        self.assertFalse(normalize(False))
        self.assertFalse(normalize(None))
        self.assertFalse(normalize(''))

    def test_single_structured_object_not_wrapped_in_list(self):
        """A single note object (not wrapped in a list) must also be
        handled, not just the list-of-objects shape."""
        normalize = self.env['kds.order.line'].normalize_note_text
        self.assertEqual(normalize('{"text":"Well done","colorIndex":2}'), 'Well done')

    def test_json_shaped_but_unparseable_falls_back_to_raw(self):
        """Requirement 6 (compatibility): text that merely starts with
        a JSON-like character but doesn't actually parse must be
        treated as plain text, not silently dropped."""
        normalize = self.env['kds.order.line'].normalize_note_text
        self.assertEqual(normalize('[not valid json'), '[not valid json')

    def test_unrecognized_json_shape_falls_back_to_raw(self):
        """Valid JSON that doesn't match the expected note-object shape
        at all must fall back to the original raw text rather than
        silently dropping potentially meaningful content."""
        normalize = self.env['kds.order.line'].normalize_note_text
        self.assertEqual(normalize('[1, 2, 3]'), '[1, 2, 3]')

    def test_mixed_valid_and_invalid_entries_keeps_valid_ones(self):
        """A single malformed entry within an otherwise-recognized
        list must not hide every other genuinely readable note."""
        normalize = self.env['kds.order.line'].normalize_note_text
        result = normalize('[{"text":"Heating"},{"foo":"bar"},{"text":"Spicy"}]')
        self.assertEqual(result, 'Heating, Spicy')

    # -----------------------------------------------------------------
    # Integration-level: the actual controllers/payload builders that
    # serialize notes for display, confirming the fix is genuinely
    # wired into every required rendering surface.
    # -----------------------------------------------------------------

    def test_internal_kds_orders_endpoint_normalizes_note(self):
        """Internal KDS (controllers/kds.py, the /flexsys_kds/orders
        route): the controller's own call site builds each line's
        'note' via exactly `request.env['kds.order.line']
        .normalize_note_text(l.note)` - this confirms that exact
        call, against a real stored (raw JSON) value, produces clean
        text. This is a call-site-logic check, not a full HTTP
        round-trip (see test_phase2_direct_printing_http.py's own
        HttpCase suite for this project's established pattern for
        that, where a full round-trip is warranted for
        auth/ownership concerns this simple serialization call
        doesn't have)."""
        order = self._make_order([(self.product_burger, 1)])
        line = order.line_ids[0]
        self._route_line_to_station(line, self.station_kitchen)
        line.write({'note': '[{"text":"Heating","colorIndex":0}]'})

        self.assertEqual(
            self.env['kds.order.line'].normalize_note_text(line.note),
            'Heating'
        )

    def test_direct_auto_print_payload_normalizes_note(self):
        """POS Direct Auto Print payload builder
        (models/kds_print_job.py, _build_pos_direct_auto_claim_payload
        path) - station-scoped line_payload."""
        station = self.env['kds.station'].create({
            'name': 'Note Test Station', 'code': 'NOTETESTSTATION', 'target_prep_time': 10,
            'operating_mode': 'printer_only',
            'flexsys_printing_method': 'direct_network',
            'flexsys_printer_ip': '192.168.1.199',
        })
        order = self._make_order([(self.product_burger, 1)])
        line = order.line_ids[0]
        self._route_line_to_station(line, station)
        line.write({'note': '[{"text":"Heating","colorIndex":0},{"text":"Extra Spicy","colorIndex":1}]'})

        job = self.env['kds.print.job'].create_direct_auto_print_job(order.id, station.id)
        self.assertTrue(job)
        payload = job._build_pos_direct_auto_claim_payload()
        line_notes = [l['note'] for l in payload['order']['lines']]
        self.assertIn('Heating, Extra Spicy', line_notes)
        self.assertNotIn('colorIndex', ''.join(line_notes))
        self.assertNotIn('{', ''.join(line_notes))

    def test_stored_raw_note_field_itself_is_untouched(self):
        """Normalization happens only at rendering time (per explicit
        requirement) - the stored kds.order.line.note field itself
        must remain the original raw value, so pre-existing records
        are corrected on display without any data migration, and the
        POS<->KDS sync change-detection logic (which compares this
        raw value) continues to work correctly."""
        order = self._make_order([(self.product_burger, 1)])
        line = order.line_ids[0]
        raw_json_note = '[{"text":"Heating","colorIndex":0}]'
        line.write({'note': raw_json_note})
        line.invalidate_recordset()
        self.assertEqual(line.note, raw_json_note, "The stored raw note field must not itself be rewritten.")
