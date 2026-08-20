# -*- coding: utf-8 -*-
"""Post-migration: archive the not-yet-real kds.order.source.tag seed
records for an existing installation, on upgrade to 19.0.7.22.0.

UI/DATA FIX ("Master Change Request", item 9, "Sources Cleanup"):
confirmed by usage check that 'pos' is the only source value this
codebase ever actually assigns to a kds.order anywhere - every other
seeded source (QR, Web, Call Center, Delivery Application, API,
FlexSys Orders) implied a live integration that doesn't actually exist
yet. data/kds_data.xml now seeds those six with active=False for a
BRAND NEW installation - but that file is loaded with noupdate="1"
(deliberately, so a genuine future customization to these records by
an administrator is never silently overwritten by a later module
upgrade), which means an EXISTING installation's already-loaded copies
of these six records would otherwise keep their old active=True value
forever, never picking up this fix on upgrade. This migration applies
the same change directly, once, for exactly that case.

Deliberately scoped to the six specific, known XML ID-backed records
this fix concerns - not "every source_tag that happens to be inactive
in matching product/POS-category data" or any other broader
heuristic - matching exactly what the corresponding data file change
does for a fresh install, so an upgrade and a fresh install both reach
the identical end state. Idempotent: safe to run again (WHERE active is
still true is the only thing it touches), and does nothing at all if
this module's own XML ID for a given record was never actually loaded
in this database to begin with (LEFT JOIN naturally excludes it).
"""
import logging

_logger = logging.getLogger(__name__)

_SOURCE_TAG_XML_IDS = (
    'order_source_tag_qr',
    'order_source_tag_web',
    'order_source_tag_call_center',
    'order_source_tag_delivery_app',
    'order_source_tag_api',
    'order_source_tag_flexsys',
)


def migrate(cr, version):
    cr.execute("""
        UPDATE kds_order_source_tag t
        SET active = false
        FROM ir_model_data d
        WHERE d.model = 'kds.order.source.tag'
          AND d.module = 'flexsys_kds'
          AND d.name = ANY(%s)
          AND d.res_id = t.id
          AND t.active IS DISTINCT FROM false
    """, (list(_SOURCE_TAG_XML_IDS),))
    _logger.info(
        "FlexSys KDS: archived %s not-yet-real kds.order.source.tag record(s) "
        "(QR/Web/Call Center/Delivery Application/API/FlexSys Orders) on this "
        "existing installation - 'pos' remains active, unaffected.", cr.rowcount)
