# -*- coding: utf-8 -*-
from odoo import fields, models


class KdsOrderSourceTag(models.Model):
    """Same idea as kds.order.type.tag, for the 'source' matching
    criterion on routing rules (Odoo POS / QR Order / Web Order / ...)."""
    _name = 'kds.order.source.tag'
    _description = 'FlexSys KDS Order Source (routing tag)'
    _order = 'sequence'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Must match a kds.order.source selection value.")
    sequence = fields.Integer(default=10)
    # UI/DATA FIX ("Master Change Request", item 9, "Sources
    # Cleanup"): confirmed by usage check that this codebase only ever
    # assigns kds.order.source = 'pos' anywhere (models/pos_order.py's
    # own _flexsys_kds_create(), the single production entry point) -
    # every other seeded source below (QR, Web, Call Center, Delivery
    # Application, API, FlexSys Orders) implies a live integration that
    # doesn't actually exist in this codebase yet, exactly the concern
    # raised ("لا تعرض للمستخدم مصادر توحي بتكامل جاهز إذا كان المصدر
    # غير مفعّل/غير مستخدم فعليًا"). `active` didn't exist as a field
    # on this model at all before this fix - added here specifically so
    # the not-yet-real sources can be archived (data/kds_data.xml) with
    # Odoo's own standard mechanism, hiding them from every normal UI
    # (routing rule tag pickers, filters) while keeping the records
    # themselves fully intact and one click away from reactivation the
    # moment a real integration for one of them actually ships - never
    # deleted, so no existing routing rule that might reference one
    # historically is ever broken by this change.
    active = fields.Boolean(default=True)

    # ODOO 19 API MIGRATION: see kds_order.py's own comment on this same
    # change for the full explanation - purely a declaration-syntax
    # change, no behavioral difference.
    _code_uniq = models.Constraint(
        'unique(code)', 'Order source code must be unique.')
