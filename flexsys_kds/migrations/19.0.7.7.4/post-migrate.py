# -*- coding: utf-8 -*-
"""Post-migration: backfill kds.order.line.last_kds_sent_qty for every
existing line on upgrade to 19.0.7.7.4.

REAL BUG FIX ("BUG-11 [fourth report] - Sequential qty_delta baseline
is still wrong at runtime"): this version introduces last_kds_sent_qty
as the new, explicit baseline for the qty_delta calculation - see that
field's own docstring in models/kds_order_line.py for the full
contract. A brand-new Float field on an existing table defaults to 0.0
for every row already in the database (Odoo's own standard behavior
for adding a column to existing records) - post_init_hook does NOT run
on a module *upgrade* (only on a fresh install), so without this
migration script, every already-active ticket on a live instance would
have last_kds_sent_qty = 0.0 the moment this upgrade completes. The
very next POS quantity edit on any of those lines would then compute
qty_delta as the FULL new quantity minus zero (e.g. "UPDATED (+3)"
instead of a correct, small delta like "+1") - a serious, silent
regression for every restaurant already running this module, not a
theoretical one.

Backfills every existing kds.order.line's own last_kds_sent_qty to
match its own current qty - the correct, safe assumption for a line
that has already been sitting in the database: whatever its current
displayed quantity is, that IS the last quantity the kitchen was
actually shown (nothing about this migration itself constitutes a new
POS sync). Idempotent: only touches rows where last_kds_sent_qty is
still at the column's own just-added default (0.0) but qty itself is
already nonzero - safe to run more than once, and skips any row an
earlier run (or a fresh install's own create()-time stamping) already
handled correctly.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE kds_order_line
        SET last_kds_sent_qty = qty
        WHERE last_kds_sent_qty = 0.0 AND qty != 0.0
    """)
    _logger.info(
        "FlexSys KDS: backfilled last_kds_sent_qty for %s existing kds.order.line "
        "row(s) to match their own current qty.", cr.rowcount)
