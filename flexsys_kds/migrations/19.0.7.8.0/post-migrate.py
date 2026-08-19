# -*- coding: utf-8 -*-
"""Post-migration: backfill kds.order.pos_closed_at for every existing
order whose linked POS order has already closed, on upgrade to
19.0.7.8.0.

REAL BUG FIX ("BUG-14 - COMPLETED Retention Must Depend on POS
Closure"): this version introduces pos_closed_at as the new anchor for
a Completed ticket's own retention timer - NULL means "the POS order
hasn't closed yet, stay visible unconditionally" (see that field's own
docstring in models/kds_order.py for the full contract). A brand-new
field defaults to NULL for every row already in the database, which is
the CORRECT state for an order whose POS side is still genuinely open -
but for an order that had ALREADY closed before this upgrade ever ran,
NULL would incorrectly mean "never start the retention timer at all",
rather than "it already closed, a while ago, before this field even
existed." Without this migration, every already-completed-and-closed
ticket on a live instance would suddenly stop expiring from the KDS
screen entirely after this upgrade, staying visible forever, since
nothing about a closed, no-longer-changing POS order would ever trigger
the write()-time stamping logic that normally sets this field going
forward.

Backfills pos_closed_at to the linked pos.order's own write_date for
every kds.order that is both 'completed' and whose linked pos.order is
already in a closed state (paid/done/invoiced) - write_date is an
imperfect proxy for "the exact moment of closure" (it updates on any
field change, not just state), but it is the best available signal for
a one-time historical backfill, and is far more correct than either
"never expires" (NULL) or "just-closed, expire fresh from right now"
(which would delay expiry for orders that actually closed long ago).
Idempotent: only touches rows where pos_closed_at is still NULL.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE kds_order ko
        SET pos_closed_at = po.write_date
        FROM pos_order po
        WHERE ko.pos_order_id = po.id
          AND ko.state = 'completed'
          AND ko.pos_closed_at IS NULL
          AND po.state IN ('paid', 'done', 'invoiced')
    """)
    _logger.info(
        "FlexSys KDS: backfilled pos_closed_at for %s existing completed kds.order "
        "row(s) whose linked POS order was already closed.", cr.rowcount)
