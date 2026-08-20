# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    # CHANGE REQUEST FIX ("POS Send-to-KDS Settings - Simplify and
    # Correct Triggers"), confirmed live: simplified from three options
    # down to the two the request explicitly asks for. The old
    # 'validation'/'submit' pair is gone - both used to trigger sync on
    # ANY backend write touching 'lines'/'state' (create, qty change,
    # product add/remove, simply viewing/re-saving the order), which is
    # exactly the "Critical Trigger Rule" violation reported: "Adding
    # products... Removing products... Changing quantities... must NOT
    # automatically synchronize the order with KDS. The synchronization
    # boundary must be the cashier's explicit action: Send or New."
    #
    # 'send' (label "On Send to KDS") replaces both - see
    # pos_order.py::_flexsys_kds_sync()'s own docstring for exactly how
    # it detects the native Send/New action rather than any backend
    # write.
    kds_send_trigger = fields.Selection([
        ('payment', 'After Payment'),
        ('send', 'When Sent from POS'),
    ], default='payment', required=True, string='Send Order to KDS',
        help=(
            # UI/DATA FIX ("Master Change Request", item 11, "Naming
            # Cleanup"): "Send to KDS On" -> "Send Order to KDS"
            # (field's own string, above), and the 'send' option's own
            # label -> "When Sent from POS" - both purely display-text
            # changes; the underlying Selection VALUES ('payment'/
            # 'send') stored in the database are completely unchanged,
            # so no existing configuration is affected in any way -
            # "لا تغيير على المنطق الحالي" is honored exactly.
            "When an order placed through this POS should reach the "
            "kitchen.\n\n"
            "'After Payment' (default): the original, safest behavior "
            "(unchanged) - the order reaches the kitchen once payment/"
            "order completion goes through.\n\n"
            "'When Sent from POS': uses Odoo's own native POS workflow, "
            "not a new custom button. With Preparation Display enabled, "
            "this is the native 'Send' action (Build/Edit Order -> Send "
            "-> FlexSys KDS). Without Preparation Display, this is the "
            "native 'New' action (Build/Edit Order -> New -> FlexSys "
            "KDS) - starting a new order finalizes/sends the current "
            "one. Either way, simply adding/removing products, "
            "changing quantities, or editing the order does NOT "
            "synchronize anything by itself - changes accumulate until "
            "the next Send/New, then sync as ADDED/UPDATED/CANCELLED "
            "all at once."
        ))

    # UI/DATA FIX ("Master Change Request", item 10, "POS Scope"):
    # "أي POS مرتبط بـ POS Configs في Station واحدة على الأقل -> يعتبر
    # داخل نطاق FlexSys KDS -> يظهر في POS Send-to-KDS Settings. POS
    # غير مرتبط بأي Station -> لا يظهر في القائمة." Confirmed live:
    # the Send-to-KDS Settings screen (kds_pos_config_views.xml) had NO
    # filtering at all - every pos.config in the entire database,
    # in-scope or not, was shown. Odoo has no built-in reverse-M2M
    # field for kds.station.pos_config_ids, so this computed field
    # provides one - purely a lightweight lookup, useful for anyone
    # inspecting a specific POS config directly. Not stored - no
    # reason to persist and keep in sync with every station edit for
    # this display-only purpose. NOTE: being unstored, this field
    # cannot be used in a search domain directly (no real database
    # column exists to query) - see _search() below for how the actual
    # Send-to-KDS Settings screen filters correctly instead.
    kds_station_ids = fields.Many2many(
        'kds.station', string='FlexSys KDS Stations', compute='_compute_kds_station_ids',
        help="The FlexSys KDS stations this POS is configured to send orders to. "
             "Empty means this POS is not currently in scope for FlexSys KDS at all.")

    def _compute_kds_station_ids(self):
        for config in self:
            config.kds_station_ids = self.env['kds.station'].search(
                [('pos_config_ids', 'in', config.id)])

    # Deliberately NOT solved by making kds_station_ids stored+queryable
    # instead: kds.station.pos_config_ids has no explicitly-named
    # relation table, so declaring a "matching" reverse field on
    # pos.config risks either guessing Odoo's own auto-generated
    # relation table name wrong, or - far more dangerously -
    # redefining the EXISTING field's own relation table name, which
    # would silently orphan every station's own existing
    # pos_config_ids links on upgrade without a migration. Neither risk
    # is acceptable for live data.
    #
    # Instead: this override only ever activates for a request that
    # explicitly opts in via context (action_kds_pos_config_send_trigger
    # below, and nothing else in this codebase) - every other caller of
    # pos.config's own search/read (POS settings, every other existing
    # screen, any other module) is completely unaffected, since the
    # context key this checks is never set anywhere else.
    #
    # REAL BUG FIX ("Batch 2 live test - Item 10 recursion crash"),
    # confirmed live: the original implementation resolved the in-scope
    # ids via `self.env['kds.station'].sudo().search([]).pos_config_ids.ids`
    # - reading `.pos_config_ids` (a Many2many field ON kds.station,
    # pointing back AT pos.config) from *inside* this very override.
    # `sudo()` elevates privilege but does NOT clear `self.env.context`
    # - the inherited `flexsys_kds_scope_only` flag was still set on
    # that inner `env`. Some part of Odoo's own internal machinery for
    # resolving a Many2many field's real records (existence-checking
    # the referenced pos.config rows) re-enters `pos.config._search()`
    # for that internal step, still carrying the SAME context flag -
    # which made THIS override fire again, which tried to resolve
    # `.pos_config_ids` again, which re-entered `_search()` again...
    # infinite recursion, exactly as reported, until the interpreter's
    # own recursion limit crashed the request.
    #
    # Fixed by never touching the ORM's own ".pos_config_ids" field-read
    # path for this lookup at all - a direct SQL query against the
    # relation table backing that Many2many field instead. This cannot
    # re-enter pos.config._search() under any circumstance, since it
    # never asks the ORM to resolve/read/exist-check any pos.config
    # recordset in the first place - it reads the raw relation table's
    # own foreign-key column directly. `field.relation`/`column1`/
    # `column2` are read from the field's own already-set-up metadata
    # (populated by Odoo itself, whether or not those names were
    # explicitly declared) rather than guessed, so this is exactly as
    # safe with respect to that table's real name as the ORM's own
    # internal Many2many read logic is - it uses the identical
    # metadata Odoo itself relies on.
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        if self.env.context.get('flexsys_kds_scope_only'):
            field = self.env['kds.station']._fields['pos_config_ids']
            self.env.cr.execute(
                'SELECT DISTINCT "%s" FROM "%s"' % (field.column2, field.relation))
            in_scope_ids = [row[0] for row in self.env.cr.fetchall()]
            domain = list(domain or []) + [('id', 'in', in_scope_ids)]
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)

