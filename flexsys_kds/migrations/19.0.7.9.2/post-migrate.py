# -*- coding: utf-8 -*-
"""Post-migration: backfill pos.order.kds_last_processed_send_signal
for every existing order already linked to a kds.order, on upgrade to
19.0.7.9.2.

REAL BUG FIX ("On Send to KDS / Subsequent Changes Bypass Send Gate"):
this version introduces kds_last_processed_send_signal as the new
tracking field that distinguishes a genuine, NEW Send from a routine
save re-carrying an already-processed last_order_preparation_change
value along - see that field's own docstring in models/pos_order.py
for the full contract. A brand-new Char field defaults to NULL for
every row already in the database. For an order that has ALREADY been
sent to KDS at least once before this upgrade (kds_order_id is set),
its own last_order_preparation_change already holds a genuinely
non-empty value from that prior Send - but its own new
kds_last_processed_send_signal starts NULL, which differs from that
existing value. The very next write to such an order after this
upgrade - even a routine one, carrying that same pre-existing value
along, not a genuine new Send - would therefore be incorrectly
recognized as a "new" Send exactly once, causing a single harmless but
unnecessary reconciliation pass (harmless because _flexsys_kds_diff_lines()
itself only ever applies genuine deltas - nothing would actually change
if the underlying POS data hadn't - but unnecessary work worth avoiding
regardless).

Backfills kds_last_processed_send_signal to match each such order's own
current last_order_preparation_change value, so the very next write is
correctly recognized as "no change since we last processed a Send" from
the moment this upgrade completes, exactly as if that value had always
been tracked. Idempotent: only touches rows where
kds_last_processed_send_signal is still NULL.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE pos_order
        SET kds_last_processed_send_signal = last_order_preparation_change
        WHERE kds_order_id IS NOT NULL
          AND kds_last_processed_send_signal IS NULL
          AND last_order_preparation_change IS NOT NULL
    """)
    _logger.info(
        "FlexSys KDS: backfilled kds_last_processed_send_signal for %s existing "
        "pos.order row(s) already linked to a kds.order.", cr.rowcount)
