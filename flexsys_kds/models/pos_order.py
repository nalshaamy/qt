# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


def _pos_note(record, default=''):
    """Read a POS order/line 'note' field defensively.

    Confirmed by a real runtime error in production: this Odoo 19 build
    does not have a 'note' field on pos.order at all
    ("'pos.order' object has no attribute 'note'"), which crashed the
    entire payment flow (not just FlexSys KDS) since this ran as part of
    order confirmation. Applied to pos.order.line reads too, defensively,
    in case that field has also been renamed/removed here and I just
    haven't hit the error for it yet - better a blank note than another
    crash blocking checkout.
    """
    return getattr(record, 'note', default) or default


def _pos_table_number(order):
    """UI/DATA FIX ("FlexSys KDS - Master Change Request", item 1,
    "Table Number - Fix"): resolves a display string for the POS
    order's own linked table, or '' for a Direct Sale order (no table)
    - "Direct Sale يبقى بدون Table Number."

    getattr(order, 'table_id', False), matching this module's own
    established defensive pattern for a field that only exists when
    pos_restaurant is installed (see _flexsys_kds_create()'s own
    identical use of getattr() for 'takeaway', right next to where
    this is called) - never assumes `table_id` exists on `order` at
    all, and never raises if it doesn't.

    table_id.table_number (an Integer) is the primary source, not
    table_id.name - confirmed directly from Odoo's own official forum
    that starting in Odoo 18, "tables can only be numbered" (free-text
    table naming was removed from core POS), making table_number the
    reliably present, stable identifier across the Odoo 18/19 versions
    this module actually targets. table_id.name is checked SECOND, only
    as a fallback if table_number itself is somehow falsy/unset - never
    the first choice, and never assumed to exist or be meaningful on
    its own.
    """
    table = getattr(order, 'table_id', False)
    if not table:
        return ''
    table_number = getattr(table, 'table_number', False)
    if table_number:
        return str(table_number)
    name = getattr(table, 'name', False)
    if name and str(name).strip():
        return str(name).strip()
    return ''


def _pos_line_variant_info(line):
    """Best-effort description of a line's selected variant/attributes
    (size, flavor, add-ons chosen at sale time), kept separate from the
    free-text customer note so the KDS card can style/label them
    differently.

    product_id.display_name usually already includes the variant's
    attribute values in parentheses (e.g. "Iced Latte (Large, Oat
    Milk)") for a true product.product variant - that's the reliable
    part. Attribute/combo selections made at the *order line* level
    (Odoo's "optional products" / custom attribute value flows) have
    used different field names across versions, so those are checked
    defensively via `_fields` rather than assumed.
    """
    product = line.product_id
    parts = []
    if product.display_name and product.name and product.display_name != product.name:
        variant_part = product.display_name.replace(product.name, '', 1).strip(' ()')
        if variant_part:
            parts.append(variant_part)
    for field_name in ('attribute_value_ids', 'custom_attribute_value_ids'):
        if field_name in line._fields:
            values = getattr(line, field_name)
            if values:
                label_field = 'display_name' if 'display_name' in values._fields else 'name'
                parts.append(', '.join(values.mapped(label_field)))
    return ' / '.join(p for p in parts if p)


def _extract_preparation_content_signature(raw):
    """REAL BUG FIX ("LIVE NETWORK TRACE - EXACT ODOO 'ORDER / SEND TO
    PREPARATION' SERVER PATH CONFIRMED"): confirmed directly from Odoo
    19's own core source (addons/point_of_sale/models/pos_order.py) that
    the server ITSELF re-stamps `metadata.serverDate` with the current
    timestamp essentially every time last_order_preparation_change gets
    written at all - `local_change['metadata']['serverDate'] =
    fields.Datetime.now().strftime(...)`, followed by
    `vals['last_order_preparation_change'] = json.dumps(local_change)`.
    This is the confirmed root cause of every earlier attempt at this
    exact problem: comparing the field's own RAW value (an earlier,
    now-removed approach comparing raw last-processed values) could
    never reliably detect "is this a genuine new Send" this way,
    because the value looks different on effectively every write
    regardless of send intent - the ever-changing timestamp swamps the
    actual content.

    Returns a signature (a JSON string) built from ONLY the genuine
    content of the value - every key except 'metadata' entirely (not
    just serverDate specifically, to stay robust against any other
    volatile key Odoo's own core might add to metadata in the future) -
    so two calls carrying the identical underlying change-set compare
    equal regardless of their own, ever-different timestamps. Returns
    None for missing/malformed/non-dict input (fails closed - missing
    a genuine Send only delays a sync, never leaks an unsent one).
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    content = {k: v for k, v in parsed.items() if k != 'metadata'}
    if not content:
        return None
    try:
        return json.dumps(content, sort_keys=True)
    except (TypeError, ValueError):
        return None


class PosOrder(models.Model):
    _inherit = 'pos.order'

    kds_order_id = fields.Many2one('kds.order', string='FlexSys KDS Order', copy=False)
    # REAL BUG FIX ("On Send to KDS / Subsequent Changes Bypass Send
    # Gate"), confirmed live: adding a product to an order that had
    # ALREADY been sent once - without pressing Send again - still
    # appeared in KDS immediately with an ADDED marker, even though the
    # initial "before first Send" case (this same file's own earlier
    # metadata-based detection) was already confirmed working
    # correctly. Root cause, confirmed directly from Odoo 19's own core
    # frontend source (addons/point_of_sale/static/src/app/services/
    # pos_store.js, sendOrderInPreparation()): order.updateLastOrderChange()
    # - the call that actually writes last_order_preparation_change to
    # the backend - is only invoked from within that same Send-handling
    # method, confirming the field genuinely is Send-specific. But the
    # field's OWN VALUE, once populated by a genuine first Send, remains
    # non-empty (with non-empty metadata) on the order going forward -
    # and Odoo's own frontend order model re-serializes and re-saves
    # this SAME, unchanged field value as part of its own routine order
    # payload on essentially every subsequent save of that order
    # (adding a product, changing a quantity, anything at all), not
    # exclusively on a genuine second Send. The earlier "non-empty
    # metadata" check could therefore no longer
    # distinguish "a fresh, second Send actually happened" from "the
    # stale, already-processed value from the FIRST Send is simply
    # being carried along again" - once an order had been sent even
    # once, every subsequent routine save looked identical to a second
    # Send.
    #
    # Fixed by tracking the exact value already processed as a genuine
    # Send here - a write is only treated as a NEW Send if the incoming
    # last_order_preparation_change value both has non-empty metadata
    # (the existing check) AND differs from this field's own stored
    # value (see _flexsys_kds_should_sync() below, which combines both
    # conditions and updates this field immediately after a successful
    # sync). A genuine second Send always produces a fresh value here
    # (Odoo's own core stamps a new print-history entry/timestamp each
    # time sendOrderInPreparation() actually runs), so this correctly
    # keeps recognizing real, repeated Sends while no longer
    # mistaking the same stale value for a new one on every routine
    # save in between.
    kds_last_processed_send_signal = fields.Char(copy=False)
    # REAL BUG FIX ("CONFIRMED LIVE NETWORK RESULT" - client's own
    # controlled A/B Network trace, the fourth and final confirmed root-
    # cause round on this exact "detect a genuine Send" problem):
    # comparing last_order_preparation_change's own content (the field
    # kds_last_processed_send_signal above exists to support) was
    # proven, by this exact live test, to be fundamentally unreliable
    # as a Send-boundary signal - an ordinary quantity edit, with no
    # Send pressed at all, was confirmed to still change that field's
    # own genuine "lines" content by the time it reaches sync_from_ui,
    # since the field appears to track the order's own current
    # unprinted-change state generally, not exclusively a genuine Send
    # event. No amount of re-comparing that field's own content -
    # raw, metadata-stripped, or otherwise - can ever reliably
    # distinguish the two, because the field's own content genuinely
    # differs in both cases.
    #
    # The client's own controlled test (Network cleared, qty edited
    # with NO Send: zero get_preparation_change calls observed;
    # immediately after pressing Send: get_preparation_change followed
    # by sync_from_ui, both observed) is the first confirmed signal
    # that is NOT derived from interpreting any field's own content at
    # all - it's the literal invocation of a specific model method,
    # confirmed to fire ONLY at the moment of a genuine Send.
    #
    # This field is the authorization flag get_preparation_change()'s
    # own override (below) sets the instant it's called - a
    # affirmative, method-invocation-based signal, not a value
    # comparison of any kind. sync_from_ui()'s own post-processing
    # consumes (clears) this flag the moment it acts on it, so a
    # SUBSEQUENT sync_from_ui call - an ordinary autosave, or any other
    # save not preceded by a fresh get_preparation_change() call -
    # finds the flag already False and correctly does nothing,
    # regardless of what last_order_preparation_change's own content
    # looks like by then. Idempotent by the same construction: several
    # get_preparation_change() calls around the same logical Send
    # (the client's own explicit requirement - "make the
    # implementation idempotent so that one real Send produces exactly
    # one KDS reconciliation even if multiple internal calls occur
    # around the same action") simply set this already-True flag to
    # True again (a harmless no-op), and the one sync_from_ui call that
    # actually follows consumes it exactly once.
    kds_preparation_change_requested = fields.Boolean(default=False, copy=False)
    # REAL BUG FIX ("CRITICAL REVIEW - 19.0.7.12.0 OFFLINE FALLBACK IS
    # NOT SAFE TO DEPLOY"): the client's own review proved a content-
    # signature-based fallback (this module's own earlier, now-removed
    # attempt at solving offline-Send recovery) is architecturally
    # unsound - "content changed != cashier pressed Send" - an ordinary
    # unsent edit and a genuine offline Send both eventually reach the
    # server with content that differs from the last committed KDS
    # snapshot, and nothing about the content alone can distinguish the
    # two. The client's own recommended fix, adopted here: "a durable
    # Send Intent / Send Generation... under this module's own
    # exclusive control... ordinary edits do NOT increment/send
    # generation, therefore cannot trigger KDS."
    #
    # kds_send_generation is that counter - a plain integer field on
    # pos.order itself, so it rides along on the SAME reliably-retried
    # sync_from_ui payload the order's own business data already uses
    # (confirmed live to survive offline recovery), exactly satisfying
    # "the intent must survive offline mode using the same local
    # persistence/retry mechanism as the POS order." Deliberately NOT
    # in `_KDS_SERVER_OWNED_FIELDS` (sync_from_ui()'s own sanitization
    # list) - unlike kds_preparation_change_requested and
    # kds_last_processed_send_signal/kds_last_processed_send_generation,
    # which are purely internal server bookkeeping the POS client must
    # never write, THIS field is specifically meant to be written BY
    # the POS client - the whole design is a durable client-supplied
    # intent marker, not a server-computed one.
    #
    # Honest, explicit status as of v7.12.1: this field, and the
    # comparison logic in _flexsys_kds_process_one_sync_from_ui_entry()
    # that reads it, were shipped as the correct, then-inert backend
    # half of this design, pending a verified frontend increment point.
    #
    # REAL BUG FIX ("BLOCKER - 19.0.7.13.0 BREAKS POS STARTUP"), current
    # status: v7.13.0's own attempt to add the frontend half -
    # `_load_pos_data_fields()` exposing this field to the POS session,
    # paired with a JS patch on `sendOrderInPreparation()` to increment
    # it - was confirmed live to crash POS startup entirely
    # ("TypeError: Cannot read properties of undefined (reading
    # 'currency_id')" inside Odoo's own PosStore.processServerData()),
    # before any Offline Send testing could even begin. Both pieces
    # were reverted immediately, in the same round this was confirmed,
    # restoring POS startup - this was treated as the release blocker
    # it is, ahead of any other work.
    #
    # Root cause not yet fully confirmed: the two sources consulted
    # while designing v7.13.0 directly conflicted on whether overriding
    # `_load_pos_data_fields()` on `pos.order` specifically (as opposed
    # to a purpose-built custom model) is safe in Odoo 19 at all - one
    # source's own documented example presented it as the standard,
    # supported mechanism; a separate, independent source explicitly
    # warned "your approach using _load_pos_data_fields() is not
    # correct for POS orders... the POS frontend crashes" for the
    # closely related Odoo 18. The live crash now confirms the second
    # source was right for this exact case, but the deeper reason why -
    # whether pos.order's own native field-loading path has additional,
    # undocumented constraints this override violated, whether the
    # crash stems from something else this delivery hasn't yet isolated
    # (a different field name collision, an ordering dependency, or a
    # separate issue entirely) - has not been independently re-verified
    # against Odoo 19's own actual runtime.
    #
    # This field itself (the database column, and the backend
    # comparison logic that reads an incoming payload's own
    # `kds_send_generation` key - see
    # `_flexsys_kds_process_one_sync_from_ui_entry()`) is UNCHANGED and
    # remains correct, per the client's own explicit instruction not to
    # redesign the backend architecture. Only the FRONTEND EXPOSURE
    # mechanism is currently missing again, and needs a different,
    # independently-verified approach before it can be safely
    # reattempted - not another guess between the two conflicting
    # sources this round's own failed attempt was based on.
    kds_send_generation = fields.Integer(default=0, copy=False)
    # REAL BUG FIX ("FINAL IMPLEMENTATION REQUEST"), requirement 6:
    # "kds_last_processed_send_generation must remain SERVER-OWNED. The
    # POS frontend must NEVER increment, decrement, reset, or
    # authoritatively write [it]." This field has never been, and must
    # never be, loaded into the POS frontend's own local order model at
    # all - unaffected by the v7.13.0 revert above, since it was never
    # part of that (or any) field-loading attempt in the first place.
    # Already protected from being written even if a stale/malicious
    # payload somehow carried it anyway, via `_KDS_SERVER_OWNED_FIELDS`
    # (`sync_from_ui()`'s own sanitization, unchanged from v7.11.3).
    kds_last_processed_send_generation = fields.Integer(default=0, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            # REAL BUG FIX ("RUNTIME FAILURE - 19.0.7.9.3 STILL BYPASSES
            # 'ON SEND TO KDS'"): see write()'s own matching, more
            # detailed comment for the full explanation of why
            # interpreting last_order_preparation_change's own content
            # was abandoned entirely, confirmed unsound by the KDS Audit
            # Log itself. is_send_write is always False here now too,
            # for the exact same reason and for consistency - 'payment'
            # mode is unaffected (its own gate never depended on
            # is_send_write to begin with); 'send' mode's own genuine
            # Send/creation now comes exclusively through
            # flexsys_kds_register_send() (this module's own frontend
            # patch calls it immediately after Odoo's own native Send
            # action completes, which itself only runs after the order
            # this same request is creating already has a real,
            # persisted id) - never inferred here from this creation's
            # own initial vals.
            order.sudo()._flexsys_kds_sync(is_send_write=False)
        return orders

    def write(self, vals):
        res = super().write(vals)
        # REAL BUG FIX, confirmed live: this gate used to check only
        # 'state' or 'lines' - but the native Send/New signal
        # (last_order_preparation_change) can arrive in a write() call
        # on its own, with neither 'state' nor 'lines' also present in
        # that same vals dict (e.g. Preparation Display's own "Send"
        # action writing only the preparation-change field). That write
        # never entered this block at all, so is_send_write was never
        # even computed and _flexsys_kds_sync() was never called - "On
        # Send to KDS" mode silently never synced anything, since the
        # one write that was SUPPOSED to trigger it didn't reach the
        # trigger check in the first place. Added explicitly to the
        # gate condition itself, not just used inside it.
        if 'state' in vals or 'lines' in vals or 'last_order_preparation_change' in vals:
            for order in self:
                order = order.sudo()
                # REAL BUG FIX ("RUNTIME FAILURE - 19.0.7.9.3 STILL
                # BYPASSES 'ON SEND TO KDS'"), confirmed live via the
                # KDS Audit Log itself (order 2629-3-000021: "Hot Italy
                # added after order was sent" - the exact message
                # _flexsys_kds_diff_lines() emits, proving this write()
                # gate, not just a frontend display gap, was still
                # reaching it): two consecutive rounds
                # (an earlier non-empty-metadata check,
                # then kds_last_processed_send_signal's own value-changed
                # check) each assumed last_order_preparation_change's own
                # content or its own change in value reliably
                # distinguishes a genuine Send from a routine save - the
                # Audit Log evidence now CONFIRMS that assumption itself
                # is false: an ordinary product-add write's own
                # last_order_preparation_change value both had non-empty
                # metadata AND differed from the previously-processed
                # one, exactly satisfying the old check's own two
                # conditions, without any genuine Send having occurred.
                # Continuing to interpret this field's own content, a
                # third time, is abandoned entirely here rather than
                # adding a fourth condition to the same fundamentally
                # unsound mechanism - "the remaining bypass is clearly
                # server-side... do not add another frontend condition."
                #
                # is_send_write is now ALWAYS False from this method,
                # for every trigger mode - 'send' mode's own genuine
                # Send signal now comes exclusively from
                # flexsys_kds_register_send() (see that method's own
                # docstring below), an explicit RPC call this module's
                # own frontend patch
                # (static/src/js/flexsys_kds_pos_send_signal.js) makes
                # immediately after Odoo's own native Send action
                # completes - never inferred from interpreting any
                # Odoo-internal field's own value here. This satisfies
                # the dev report's own explicit architecture requirement
                # verbatim: "the backend reconciliation must be gated by
                # an explicit 'sent generation / committed snapshot'
                # value... reconcile only against the last POS state
                # explicitly committed through On Send to KDS" - a plain
                # write() to this order, regardless of its own vals'
                # content, can structurally never trigger
                # _flexsys_kds_diff_lines() on its own again.
                is_send_write = False
                # REAL BUG FIX ("BUG-14 - COMPLETED Retention Must
                # Depend on POS Closure"): stamps kds.order.pos_closed_at
                # the moment this order's own state is observed
                # transitioning into a closed state - see that field's
                # own docstring (kds_order.py) for the complete
                # rationale. Checked first, before the cancel/sync
                # dispatch below, and independent of it - closure needs
                # recording regardless of which branch handles the rest
                # of this write. `not order.kds_order_id.pos_closed_at`
                # guards against overwriting an earlier closure moment
                # with a later one (e.g. paid -> done -> invoiced as
                # separate writes) - the FIRST genuine closure is the
                # one that should anchor the retention timer.
                #
                # REAL BUG FIX ("CANCELLED FILTER CLASSIFICATION +
                # RETENTION LIFECYCLE", Issue 2), found via this
                # module's own re-verification of the previously-
                # approved pos_closed_at rule (not a confirmed report
                # detail, but a genuine gap this review surfaced): the
                # closed-state set here never included 'cancel' - a POS
                # order that gets CANCELLED outright (never paid) is
                # unambiguously no longer "active/open" - it's
                # terminated, exactly the same as a paid one - yet its
                # own linked kds.order would never have pos_closed_at
                # stamped under the old condition, meaning any CANCELLED
                # KDS ticket linked to it would never become eligible
                # for retention at all, staying visible in ALL forever.
                # 'cancel' is now included alongside the payment-closed
                # states.
                if (vals.get('state') in ('paid', 'done', 'invoiced', 'cancel')
                        and order.kds_order_id and not order.kds_order_id.pos_closed_at):
                    order.kds_order_id.pos_closed_at = fields.Datetime.now()
                if vals.get('state') == 'cancel':
                    order._flexsys_kds_cancel()
                else:
                    order._flexsys_kds_sync(is_send_write=is_send_write)
        return res

    def flexsys_kds_register_send(self):
        """REAL BUG FIX ("On Send to KDS / Subsequent Changes Bypass Send
        Gate"), confirmed STILL reproducing live even after two rounds of
        purely backend-side attempts to infer a genuine Send from
        last_order_preparation_change's own content
        (an earlier non-empty-metadata check, then
        kds_last_processed_send_signal's own value-changed check) - a
        real product was still added and appeared in KDS as ADDED with
        neither Send nor New pressed on an already-committed ticket.

        Both earlier attempts shared one root assumption: that
        last_order_preparation_change's own value, or its own change in
        value, reliably distinguishes a genuine Send from an ordinary
        save. Confirmed directly from Odoo 19's own core frontend source
        that order.updateLastOrderChange() - the call that writes this
        field - is only invoked from within sendOrderInPreparation()
        itself, meaning the field IS Send-specific in origin - but
        nothing in that source confirms Odoo's own frontend order model
        doesn't ALSO re-serialize that same field's own current value as
        part of its own routine, full-order save payload on every
        subsequent write, independent of whether a genuine Send actually
        triggered THIS SPECIFIC write. Continuing to guess at this
        field's own backend-visible behavior, a third time, is no longer
        a defensible strategy.

        This method is therefore the deliberately different approach:
        an explicit, unambiguous signal this module controls directly,
        set by its own frontend patch
        (static/src/js/flexsys_kds_pos_send_signal.js) immediately after
        Odoo's own native sendOrderInPreparation() completes - not
        inferred from interpreting any Odoo-internal field's own content
        or change-in-value at all. The mere fact that this method was
        called IS the signal; no further interpretation is needed here.

        Public RPC entry point (called via the ORM from the frontend
        patch) - deliberately no bypass_check/permission gate beyond
        Odoo's own standard write-access check on pos.order (any POS
        user actively working an order already has that), matching the
        same "the cashier's own explicit action is the authorization"
        principle this entire feature exists to enforce; sudo() is used
        internally only so the automated KDS sync itself isn't
        separately gated by a station assignment that has nothing to do
        with the person ringing up the sale (same reasoning as every
        other sudo() call in this module).
        """
        for order in self.sudo():
            order._flexsys_kds_sync(is_send_write=True)

    def get_preparation_change(self):
        """REAL BUG FIX ("CONFIRMED LIVE NETWORK RESULT" - the fourth
        confirmed root-cause round on this exact "detect a genuine
        Send" problem): confirmed via the client's own controlled A/B
        Network trace - Network cleared, then a quantity edit with NO
        Send pressed produced ZERO calls to `get_preparation_change`;
        immediately after actually pressing Send,
        `get_preparation_change` fired, directly followed by
        `sync_from_ui` - `pos.order.get_preparation_change()` is
        therefore the first confirmed signal that is NOT derived from
        interpreting any field's own content at all (every earlier
        attempt at this exact problem was: presence of
        last_order_preparation_change, then its own non-empty metadata,
        then a content-only signature comparison - all three
        eventually confirmed unreliable by live testing, since that
        field's own content genuinely differs between a routine edit
        and a genuine Send, making any comparison of it fundamentally
        unable to distinguish the two). This is the literal invocation
        of a specific model method, itself the actual signal - no
        interpretation needed.

        REAL BUG FIX ("CRITICAL REVIEW - 19.0.7.11.1"), corrected here:
        the two immediately preceding rounds (v7.11.0, v7.11.1) wrongly
        decorated this override `@api.model` and added an `args[0]`
        record-id resolver, reasoning from the live Network trace's own
        `args: [278696]` representation. The client's own direct
        citation of Odoo 19's actual core source proves that
        interpretation wrong: the native method is
        `def get_preparation_change(self): self.ensure_one(); return
        {...}` - an ordinary instance method with NO `@api.model`,
        operating on a single concrete record via `self`, exactly as
        Odoo's own standard convention for a record-level method works.
        The Network trace's own `args: [278696]` is the JSON-RPC wire
        representation of `call_kw`'s own dispatch mechanism (record
        ids passed as part of how the RPC layer resolves and calls the
        method on a concrete recordset), not evidence about the actual
        Python method's own decorator or signature - correctly
        distinguishing "what the wire protocol shows" from "what the
        Python method contract actually is" was the mistake the prior
        two rounds made. `self` is therefore ALWAYS the correct order
        directly here - no resolver, no args parsing, no `@api.model`
        needed at all. The now-unnecessary
        `_flexsys_kds_resolve_order_from_preparation_change_args()`
        helper (and its own args/list-shape guessing) has been removed
        entirely, not left in place unused - it existed specifically to
        compensate for a self-inflicted signature mismatch that no
        longer exists.

        See `kds_preparation_change_requested`'s own field docstring
        (just above this class's own start) for the complete
        authorization-flag mechanism this sets, and
        `sync_from_ui()`'s own docstring immediately below for how that
        flag is consumed.

        Deliberately minimal and defensive, matching this module's own
        established pattern for every prior hook attempt:
        `super().get_preparation_change()` is always called first, with
        the exact native signature (no arguments beyond `self`) - and
        its own result always returned completely unmodified; the
        authorization-flag write is wrapped in its own try/except,
        entirely separate from the native call, so a failure here can
        never affect the actual preparation-change computation this
        method's own native behavior provides.
        """
        result = super().get_preparation_change()
        try:
            if self:
                self.sudo().write({'kds_preparation_change_requested': True})
                _logger.info(
                    "FlexSys KDS: get_preparation_change() authorized order #%s",
                    self.id)
            else:
                _logger.info(
                    "FlexSys KDS: get_preparation_change() called on an empty "
                    "recordset - unexpected, given the native method's own "
                    "self.ensure_one() call should make this impossible; no order "
                    "to authorize.")
        except Exception:
            _logger.exception(
                "FlexSys KDS: failed to set kds_preparation_change_requested after a "
                "genuine get_preparation_change() call; native preparation-change "
                "computation itself was not affected.")
        return result

    @api.model
    def sync_from_ui(self, orders, *args, **kwargs):
        """REAL BUG FIX ("LIVE NETWORK TRACE - EXACT ODOO 'ORDER / SEND
        TO PREPARATION' SERVER PATH CONFIRMED"): the client's own live
        browser Network trace confirmed the actual RPC the "Order"
        confirmation-dialog action makes is `pos.order.sync_from_ui`
        (not the sendOrderInPreparation()/updateLastOrderChange()
        frontend methods the two earlier patches hooked - confirmed by
        the KDS Audit Log itself showing ZERO events for this action,
        meaning neither frontend hook fired at all for this specific UI
        path) - and that the request's own payload carries
        last_order_preparation_change directly, containing genuine
        content (a real "lines" dict with product/quantity data), not
        an empty placeholder.

        This is the authoritative, confirmed-from-a-live-trace
        server-side entry point every save from the POS frontend goes
        through - including, but not limited to, both the normal Send
        button and the confirmation dialog's "Order" action - so gating
        here, rather than continuing to guess at which specific
        frontend method a given UI action calls, is no longer a guess:
        it's what the actual traffic shows.

        REAL BUG FIX ("CONFIRMED LIVE NETWORK RESULT"), confirmed by
        live testing to supersede this docstring's own next paragraph
        below: genuine-Send detection is no longer based on
        _extract_preparation_content_signature()'s own content
        comparison at all - proven, by the client's own controlled
        test, that an ordinary quantity edit with no Send pressed still
        genuinely changes last_order_preparation_change's own content
        by the time it reaches this method, making any comparison of
        that field's own content fundamentally unable to distinguish a
        routine edit from a genuine Send. Detection is now based
        exclusively on `kds_preparation_change_requested` - the
        method-invocation-based flag `get_preparation_change()`'s own
        override (above) sets, consumed (cleared) here the moment it's
        acted on. The content-signature machinery
        (`_extract_preparation_content_signature()`,
        `kds_last_processed_send_signal`) is left in place, not
        removed, but is no longer part of the authorization decision
        itself - see `_flexsys_kds_process_one_sync_from_ui_entry()`'s
        own updated docstring for exactly how it's still used now
        (content for the actual delta, never for deciding whether to
        act at all).

        [Historical, superseded: "Genuine-Send detection is NOT based
        on last_order_preparation_change's own raw value or presence
        (both already confirmed unreliable by three prior rounds) -
        it's based on _extract_preparation_content_signature()'s own
        content-only comparison..." - this reasoning was itself the
        NEXT thing confirmed unreliable, by the exact live test that
        prompted this current fix. Left visible here deliberately, not
        deleted, as an honest record of the actual investigation
        history rather than presenting the final answer as though it
        were obvious from the start.]

        Idempotent by construction: `kds_preparation_change_requested`
        is consumed (set back to `False`) the moment
        `_flexsys_kds_process_one_sync_from_ui_entry()` acts on it - a
        subsequent `sync_from_ui` call not preceded by a fresh
        `get_preparation_change()` call finds the flag already `False`
        and does nothing, regardless of that call's own
        last_order_preparation_change content. Several
        `get_preparation_change()` calls around the same logical Send
        (the client's own explicit requirement) simply set an
        already-`True` flag to `True` again - harmless - and the one
        `sync_from_ui` call that follows consumes it exactly once.

        The KDS-relevant post-processing below is best-effort and
        strictly additive - super().sync_from_ui(orders)'s own result is
        always computed first and always returned completely
        unmodified; a failure in this module's own post-processing
        (malformed order dict, unexpected shape, anything at all) is
        caught and logged, never allowed to affect the actual order-
        saving flow every POS session depends on.

        REAL BUG FIX ("ROOT CAUSE EVIDENCE - SEND FLAG IS BEING
        OVERWRITTEN BY POS sync_from_ui"), confirmed via the client's
        own live Network evidence: the incoming `orders` payload was
        confirmed to itself carry `kds_preparation_change_requested:
        false` and `kds_last_processed_send_signal: false` - Odoo's own
        POS frontend evidently loads these two fields into its own
        local order model (since they're defined directly on
        `pos.order`, with no explicit exclusion from whatever mechanism
        the frontend uses to decide which fields to track and write
        back), and re-sends its own stale, locally-cached value on
        every save - overwriting the server-side `True` this module's
        own `get_preparation_change()` override had JUST set, before
        this method's own post-processing ever got a chance to consume
        it.

        These two fields are internal, server-owned KDS control state -
        the POS frontend must never be authoritative for them, and
        `super().sync_from_ui()`'s own native processing must never
        even see them in the first place, regardless of how its own
        internal write logic works. `orders` is sanitized here -
        stripping both fields from every order dict's own top level and
        from any nested `data` sub-dict (matching the same two possible
        shapes this module's own post-processing already defends
        against elsewhere) - BEFORE `super().sync_from_ui()` is called,
        not after: this guarantees the native method can never persist
        a stale, frontend-supplied value for either field, independent
        of whatever internal write() calls it makes. Sanitizes a
        shallow copy of each order dict, never mutating the caller's
        own original `orders` list/dicts in place.

        See `_flexsys_kds_sanitize_orders_payload()`'s own docstring
        for the full explanation of why this sanitization step is
        currently the primary protection - a root-cause-level fix
        (excluding these fields from what the POS frontend ever loads
        in the first place, via `_load_pos_data_fields()`) was
        considered in an earlier round but not pursued, and a separate,
        unrelated attempt to use that same override for a different
        field (`kds_send_generation`) was confirmed live to crash POS
        startup entirely - see that field's own docstring
        (`models/pos_order.py`, near this class's own start) for the
        complete account. This sanitization step therefore remains the
        sole protection for `kds_preparation_change_requested` and
        `kds_last_processed_send_signal`/`kds_last_processed_send_generation`,
        not merely a defensive backstop alongside a field-loading
        exclusion that does not currently exist.

        REAL BUG FIX ("DIRECT SALE SEND FLOW NOT REACHING KDS"),
        confirmed via the client's own live A/B Network trace: Direct
        Sale orders (created without a table - Odoo 19's own confirmed
        "New Order" action on the Floor plan view) never call
        `get_preparation_change()` at all when Send is pressed -
        confirming that method is NOT a universal Send signal across
        every POS flow, only the restaurant/table one it was originally
        confirmed against. The client's own trace instead found a
        second, genuine Send signal specific to this flow: the
        `sync_from_ui` call's own RPC context carries `preparation`
        (present) together with `current_order_uuid` (matching the
        specific order being sent) - confirmed absent entirely for an
        ordinary edit with no Send pressed.

        REAL BUG FIX ("ملاحظة إصلاح حرجة - Direct Sale لا يصل إلى
        KDS"), correcting v7.14.0's own extraction mistake: this
        context is NOT delivered as a `context=` keyword argument
        inside `**kwargs` at all, despite being genuinely present in
        the wire payload the client's own Network inspection confirmed
        - `context` is Odoo's own standard RPC-call context (the same
        mechanism that carries `lang`, `tz`, `active_id`, and so on on
        every RPC call), consumed by Odoo's own `call_kw` dispatch layer
        and applied to `self.env.context` via `with_context(...)`
        BEFORE this model method is ever invoked. `self.env.context` is
        therefore the correct place to read it - see the code just
        below, and `_flexsys_kds_process_one_sync_from_ui_entry()`'s
        own docstring for the complete authorization logic this feeds
        into. The `context` dict, wherever it's actually found, is
        always passed through unmodified - never written back or
        interpreted at this level.
        """
        sanitized_orders = self._flexsys_kds_sanitize_orders_payload(orders)
        result = super().sync_from_ui(sanitized_orders, *args, **kwargs)
        try:
            # REAL BUG FIX ("ملاحظة إصلاح حرجة - Direct Sale لا يصل إلى
            # KDS"), confirmed via the client's own server-log evidence:
            # v7.14.0's own extraction (`kwargs.get('context')`) never
            # actually found the data, even though the client's own
            # Network payload inspection confirmed `context.preparation`
            # and `context.current_order_uuid` genuinely present on the
            # wire. Root cause: Odoo's own standard RPC dispatch
            # mechanism (`call_kw`) treats an incoming `context` key as
            # the SAME context every RPC call can carry (`lang`, `tz`,
            # `active_id`, and so on) - it is consumed by that dispatch
            # layer and applied to `self.env.context` via
            # `with_context(...)` BEFORE this model method is ever
            # invoked, not delivered as a `context=` keyword argument
            # inside `**kwargs` at all. `kwargs.get('context')`
            # therefore always found nothing, regardless of what the
            # actual wire payload carried - explaining exactly the
            # observed server log
            # (`direct_sale_context_present=False`,
            # `direct_sale_uuid_match=False`) despite the client's own
            # confirmed-correct Network payload.
            #
            # Fixed by reading `self.env.context` instead - the correct,
            # standard way to access an incoming RPC call's own context
            # from within any Odoo model method - with the original
            # `kwargs.get('context')` kept as a secondary, harmless
            # fallback in case some other call path genuinely does pass
            # it as an explicit keyword argument instead (covers both
            # shapes without assuming either one exclusively).
            context = self.env.context or (
                kwargs.get('context') if isinstance(kwargs, dict) else None)
            self._flexsys_kds_process_sync_from_ui(orders, context=context)
        except Exception:
            _logger.exception("FlexSys KDS: sync_from_ui post-processing failed; "
                               "native POS sync itself was not affected.")
        return result

    # REAL BUG FIX ("CRITICAL REVIEW - 19.0.7.12.0 OFFLINE FALLBACK IS
    # NOT SAFE TO DEPLOY"): kds_last_processed_send_generation added -
    # purely internal server bookkeeping tracking what this module has
    # already processed, exactly like kds_last_processed_send_signal;
    # the POS client must never be authoritative for it. Deliberately
    # does NOT include kds_send_generation itself here - see that
    # field's own docstring (just above the class's own start) for why
    # it's the one field in this whole scheme specifically meant to be
    # writable by the POS client.
    _KDS_SERVER_OWNED_FIELDS = (
        'kds_preparation_change_requested', 'kds_last_processed_send_signal',
        'kds_last_processed_send_generation',
    )

    @api.model
    def _flexsys_kds_sanitize_orders_payload(self, orders):
        """REAL BUG FIX ("ROOT CAUSE EVIDENCE - SEND FLAG IS BEING
        OVERWRITTEN BY POS sync_from_ui"): strips this module's own
        server-owned KDS control fields
        (`_KDS_SERVER_OWNED_FIELDS` above) from every order dict in the
        incoming `orders` payload - both from each dict's own top
        level and from any nested `data` sub-dict - before it's ever
        passed to `super().sync_from_ui()`. See `sync_from_ui()`'s own
        docstring, just above, for the complete root-cause explanation.

        Returns a NEW list of shallow-copied dicts - the caller's own
        original `orders` argument (and each of its own dict elements)
        is never mutated, so this module's own post-processing
        (`_flexsys_kds_process_sync_from_ui()`, called separately, on
        the ORIGINAL `orders`) still sees whatever
        `last_order_preparation_change` content the real payload
        carried, unaffected by this sanitization step, which only ever
        removes the two specific KDS-owned keys, nothing else.

        Deliberately defensive against unexpected shapes: a non-dict
        entry in `orders` is passed through completely unchanged
        (nothing to sanitize, and no reason to let a shape this method
        doesn't recognize block the native sync entirely) - never
        raises.
        """
        sanitized = []
        for order_data in (orders or []):
            if not isinstance(order_data, dict):
                sanitized.append(order_data)
                continue
            entry = dict(order_data)
            for field_name in self._KDS_SERVER_OWNED_FIELDS:
                entry.pop(field_name, None)
            nested_data = entry.get('data')
            if isinstance(nested_data, dict):
                nested_copy = dict(nested_data)
                for field_name in self._KDS_SERVER_OWNED_FIELDS:
                    nested_copy.pop(field_name, None)
                entry['data'] = nested_copy
            sanitized.append(entry)
        return sanitized

    def _flexsys_kds_process_sync_from_ui(self, orders, context=None):
        """REAL BUG FIX ("Live test result - post-send modification is
        still not propagated to KDS"), confirmed live via Network trace
        (get_preparation_change -> sync_from_ui, both HTTP 200) on a
        SECOND Send to an order already linked to a kds.order: this
        method's own earlier version had two real, independently
        confirmed problems, found by re-reading its own logic line by
        line rather than guessing a fourth mechanism:

        1. `order_data.get('uuid') or order_data.get('id')` then
           searching `[('uuid', '=', order_uuid)]` unconditionally -
           if a given sync_from_ui payload shape ever omits 'uuid' for
           an update (as opposed to an initial create) and falls back
           to 'id' (an integer primary key), searching a Char `uuid`
           field for an integer value can never match anything - the
           record lookup silently fails and this order is skipped
           entirely, with no signal that anything went wrong.

        2. The single try/except this method's own caller
           (sync_from_ui() above) wraps around the ENTIRE call meant
           one order's own unexpected shape or error could silently
           abort processing for every OTHER order in the same batch
           too - never isolated per order.

        Both fixed here: 'id' (an int) is now looked up via `browse()`
        directly, never through the `uuid` field; 'uuid' (a string) via
        `search()` as before; each order in the batch is now processed
        inside its own try/except, so one order's own failure can never
        prevent any other order in the same sync_from_ui call from
        being correctly processed.

        Also added: structured info-level logging at every decision
        point (payload received, authorization flag state, record
        resolved or not) - this is the fourth confirmed root-cause
        round on this exact "detect a genuine Send" problem; this
        logging exists specifically so any future investigation has
        real server-side log evidence to work from instead of another
        guess. Deliberately kept even after this fix is confirmed
        working, at a low enough level (info, not warning) that it's
        cheap to leave in place - genuinely useful audit trail for a
        "why didn't KDS update" question either way, not just a
        temporary debugging aid to be stripped out later.

        REAL BUG FIX ("DIRECT SALE SEND FLOW NOT REACHING KDS"):
        `context` (the `sync_from_ui` call's own `kwargs['context']`,
        confirmed live to carry the Direct Sale Send signal - see
        `sync_from_ui()`'s own docstring above) is passed through to
        each entry's own processing unmodified - never read, written,
        or interpreted at this level; only
        `_flexsys_kds_process_one_sync_from_ui_entry()` acts on it.

        REAL BUG FIX ("نتيجة الاختبار الحي - Table Send"): the batch's
        own size (`len(orders)`) is computed once here and passed
        through to each entry's own processing alongside `context` -
        needed for the conservative Table-flow fallback authorization
        path; see that method's own docstring for the complete
        explanation and its own explicit, narrow scope.
        """
        self = self.sudo()
        batch_size = len(orders or [])
        for order_data in (orders or []):
            try:
                self._flexsys_kds_process_one_sync_from_ui_entry(
                    order_data, context=context, batch_size=batch_size)
            except Exception:
                _logger.exception(
                    "FlexSys KDS: failed processing one sync_from_ui order entry "
                    "(isolated to this entry only - other orders in the same "
                    "batch are unaffected). Entry: %r", order_data)

    def _flexsys_kds_process_one_sync_from_ui_entry(self, order_data, context=None, batch_size=None):
        """REAL BUG FIX ("CONFIRMED LIVE NETWORK RESULT"): authorization
        is based exclusively on `kds_preparation_change_requested` (set
        by `get_preparation_change()`'s own override, consumed here) -
        never on `last_order_preparation_change`'s own content,
        confirmed unreliable for that purpose by the client's own live
        test. The content-signature machinery below
        (`_extract_preparation_content_signature()`,
        `kds_last_processed_send_signal`) is kept, but purely as a
        diagnostic record of what content a given authorized Send
        carried - it plays no role in the authorization decision
        itself.

        REAL BUG FIX ("CRITICAL REVIEW - 19.0.7.12.0 OFFLINE FALLBACK
        IS NOT SAFE TO DEPLOY"), a genuine architectural correction the
        client's own review caught before this module ever shipped the
        unsafe version to a live instance: v7.12.0's own content-
        signature fallback (added to address the confirmed offline-Send
        data-loss bug - see kds_send_generation's own field docstring
        below for the currently-correct fix for that specific problem)
        was itself REMOVED here, not merely adjusted, because the
        client's own review proved it architecturally unsound, not just
        imperfect: "content changed != cashier pressed Send" - an
        ordinary, unsent quantity edit and a genuine offline Send both
        eventually reach the server through sync_from_ui with content
        that differs from the last committed KDS snapshot, and nothing
        about the content itself can distinguish the two. Continuing to
        rely on any comparison of last_order_preparation_change's own
        content - which is exactly what this specific fallback still
        was, despite the "offline-recovery" framing - reintroduced the
        exact "ordinary edit leaks to KDS" bug this project spent
        several earlier rounds (v7.9.1 through v7.11.3) confirming and
        fixing. A backend-only fallback based on content difference
        alone can never safely provide both "no KDS sync for ordinary
        unsent edits" and "guaranteed recovery of an offline Send" at
        the same time - the client's own stated conclusion, and this
        module's own correction agrees with it completely.

        The durable fix for offline-Send recovery is
        `kds_send_generation` instead (see that field's own docstring)
        - a counter under this module's own exclusive control, never
        touched by an ordinary edit, that rides along on the SAME
        reliably-retried sync_from_ui payload the order's own business
        data already uses. Authorization here now checks that field's
        own genuine change, not last_order_preparation_change's.

        REAL BUG FIX ("SECOND CRITICAL ISSUE - AUTHORIZATION IS
        CONSUMED BEFORE DELIVERY"), also from the same review: the
        authorization marker(s) used to be cleared/updated BEFORE
        `_flexsys_kds_sync()` was called - if that call then failed for
        any reason, the Send would have already been marked processed,
        permanently losing it with no possibility of retry. Corrected
        here: `_flexsys_kds_sync()` is now called FIRST; the
        authorization marker(s) are only cleared/updated AFTER it
        completes successfully (i.e. without raising) - "successful
        processing must be the point at which the send generation is
        acknowledged/consumed... if sync fails, keep generation
        pending/retryable," exactly the client's own required
        principle. A retried sync_from_ui call for a Send whose own
        KDS-side processing previously failed will now correctly
        re-attempt it, rather than silently treating it as already
        handled.
        """
        if not isinstance(order_data, dict):
            _logger.info("FlexSys KDS sync_from_ui: skipped a non-dict order entry: %r", order_data)
            return
        # Defensive: the confirmed live payload carries
        # last_order_preparation_change at the top level of each order
        # dict - but also checks a nested 'data' key as a fallback, in
        # case a different sync_from_ui call shape (e.g. an update to
        # an already-persisted order, as opposed to the initial create
        # this was first confirmed against) nests it differently.
        raw = order_data.get('last_order_preparation_change')
        if raw is None and isinstance(order_data.get('data'), dict):
            raw = order_data['data'].get('last_order_preparation_change')
        signature = _extract_preparation_content_signature(raw)
        order_id = order_data.get('id')
        order_uuid = order_data.get('uuid')
        if not order_uuid and isinstance(order_data.get('data'), dict):
            order_uuid = order_data['data'].get('uuid')
        order = self.env['pos.order']
        # 'id' (an int - an already-persisted, existing order being
        # updated) is looked up via browse(), never through the uuid
        # field - see this method's own docstring for the confirmed bug
        # this fixes. Tried first: sync_from_ui's own core lookup
        # pattern (confirmed from Odoo 19's own source) uses uuid, but
        # an update payload for an order that already has a real
        # database id is at least as likely, if not more so, to carry
        # that id directly.
        if isinstance(order_id, int) and order_id > 0:
            order = self.env['pos.order'].browse(order_id).exists()
        if not order and order_uuid:
            order = self.env['pos.order'].search(
                [('uuid', '=', order_uuid)], limit=1, order='id desc')
        if not order:
            _logger.info(
                "FlexSys KDS sync_from_ui: could not resolve a pos.order record "
                "for id=%r uuid=%r - skipped.", order_id, order_uuid)
            return
        # kds_send_generation (see that field's own docstring): the
        # currently-correct, durable signal for a genuine Send that
        # survives offline recovery, exclusively under this module's
        # own control - never touched by an ordinary edit. Read from
        # the incoming payload defensively (top-level or nested 'data',
        # matching every other field this method already reads this
        # way); compared against the order's own last-processed value.
        # Currently inert in practice until a verified frontend
        # increment exists (see that field's own docstring for why it
        # is intentionally shipped this way) - the comparison itself is
        # always safe: with no frontend yet incrementing it, incoming
        # and last-processed both stay at their shared default and
        # never authorize anything on their own.
        incoming_generation = order_data.get('kds_send_generation')
        if incoming_generation is None and isinstance(order_data.get('data'), dict):
            incoming_generation = order_data['data'].get('kds_send_generation')
        authorized_via_flag = bool(order.kds_preparation_change_requested)
        authorized_via_generation = (
            isinstance(incoming_generation, int)
            and incoming_generation > order.kds_last_processed_send_generation
        )
        # REAL BUG FIX ("DIRECT SALE SEND FLOW NOT REACHING KDS"),
        # confirmed via the client's own live A/B Network trace: Direct
        # Sale orders (no table) never call get_preparation_change() at
        # all - confirming that method is not a universal Send signal.
        # The confirmed replacement signal for THIS flow specifically:
        # sync_from_ui's own kwargs['context'] carries a genuinely
        # present 'preparation' key together with 'current_order_uuid'
        # - both confirmed absent for an ordinary edit with no Send.
        #
        # REAL BUG FIX ("DESIGN APPROVED WITH TWO IMPORTANT
        # CONSTRAINTS") - the client's own explicit scope correction to
        # this design, applied exactly as specified: authorization is
        # NOT granted to every order in the sync_from_ui batch merely
        # because context['preparation'] exists somewhere in the call -
        # it is granted ONLY to the one order whose own uuid matches
        # context['current_order_uuid'] exactly. Any other order that
        # might theoretically be present in the same batch is left
        # completely untouched by this specific authorization path,
        # even if the batch-level context still carries a genuine
        # preparation key - "Only that matching order should receive
        # the Direct Sale Send authorization."
        context_preparation_present = bool(context) and bool(context.get('preparation'))
        context_current_order_uuid = context.get('current_order_uuid') if context else None
        authorized_via_direct_sale_context = (
            context_preparation_present
            and context_current_order_uuid
            and order_uuid
            and order_uuid == context_current_order_uuid
        )
        # REAL BUG FIX ("DESIGN APPROVED..."), de-duplication rule -
        # applied ONLY to this new authorization path, which (unlike
        # the flag and generation paths above, each of which already
        # has its own dedicated consume/advance mechanism making a
        # repeat impossible on its own) has no other guard against a
        # repeated delivery of the SAME already-processed Send:
        # "trusted Send authorization -> compare signature -> same
        # signature = duplicate delivery, ignore -> different signature
        # = process." The signature comparison here is EXCLUSIVELY a
        # de-duplication check on an ALREADY-established authorization
        # - it is never itself the reason authorization was granted;
        # `authorized_via_direct_sale_context` above was already fully
        # decided, using only the explicit context signal, before this
        # comparison is even reached. "The signature must remain
        # deduplication only, never authorization" - a genuinely
        # different content signature does NOT grant authorization on
        # its own anywhere in this method; only a context match (this
        # path), the flag (get_preparation_change), or a generation
        # advance can.
        authorized_via_direct_sale = (
            authorized_via_direct_sale_context
            and signature
            and signature != order.kds_last_processed_send_signal
        )
        # REAL BUG FIX ("نتيجة الاختبار الحي - Table Send"), confirmed
        # live: for a genuine Table Send, `context.preparation` was
        # confirmed present, but `context.current_order_uuid` did NOT
        # match the order actually carried in the sync_from_ui payload
        # (`ce7e4642-...` vs `dcc344a3-...`) - the field appears to
        # reflect some other notion of "currently active order in the
        # cashier's own UI" rather than reliably identifying which
        # specific order in THIS payload is being sent, at least for
        # the Table flow. The client's own explicit design, accepted
        # with an explicit conservative constraint after confirming
        # `len(orders) == 1` for the one live Table Send trace captured
        # so far (NOT proven true for every possible Table Send,
        # deliberately not assumed to be): when `preparation` is
        # present but the uuid does not match, and this sync_from_ui
        # call's own entire batch contains EXACTLY one order, that one
        # order is authorized - "if the payload contains more than one
        # Order, do not authorize any entry through this path... do not
        # widen the logic to guess which Order in a multi-order batch."
        # A multi-order batch under this exact condition is left
        # completely unauthorized via this path - `authorized_via_flag`
        # and `authorized_via_generation` remain fully available as
        # normal for any such order.
        #
        # The existing uuid-match path above is completely untouched -
        # still the FIRST, preferred check, still exactly what
        # authorizes Direct Sale correctly; this is purely an
        # additional, narrower fallback for when that check fails but
        # the batch's own shape makes the intended order unambiguous
        # anyway. The same signature-based de-duplication rule applies
        # here identically - a repeated delivery of the same
        # already-processed content is still correctly recognized and
        # skipped, never re-processed.
        authorized_via_table_single_order_fallback = (
            context_preparation_present
            and not authorized_via_direct_sale_context
            and batch_size == 1
            and signature
            and signature != order.kds_last_processed_send_signal
        )
        _logger.info(
            "FlexSys KDS sync_from_ui: order #%s kds_preparation_change_requested=%s "
            "incoming_generation=%r last_processed_generation=%s "
            "direct_sale_context_present=%s direct_sale_uuid_match=%s "
            "batch_size=%r table_single_order_fallback=%s has_content_signature=%s",
            order.id, order.kds_preparation_change_requested, incoming_generation,
            order.kds_last_processed_send_generation, context_preparation_present,
            authorized_via_direct_sale_context, batch_size,
            authorized_via_table_single_order_fallback, bool(signature))
        if (
            not authorized_via_flag
            and not authorized_via_generation
            and not authorized_via_direct_sale
            and not authorized_via_table_single_order_fallback
        ):
            if context_preparation_present and not authorized_via_direct_sale_context and batch_size != 1:
                _logger.info(
                    "FlexSys KDS sync_from_ui: order #%s - preparation context present "
                    "but uuid did not match and this batch contains more than one order "
                    "(batch_size=%r) - correctly left unauthorized rather than guessing "
                    "which order in a multi-order batch was intended. Skipped.",
                    order.id, batch_size)
            elif (
                (authorized_via_direct_sale_context or batch_size == 1)
                and context_preparation_present
            ):
                _logger.info(
                    "FlexSys KDS sync_from_ui: order #%s - preparation context matched "
                    "(via uuid or the single-order fallback), but the content signature "
                    "is unchanged from the last processed Send - correctly treated as a "
                    "duplicate delivery, not a new Send. Skipped.", order.id)
            else:
                _logger.info(
                    "FlexSys KDS sync_from_ui: order #%s - no prior get_preparation_change() "
                    "call recorded, no new kds_send_generation, and no matching Direct Sale "
                    "context either, correctly treated as an ordinary save, not a genuine "
                    "Send. Skipped.", order.id)
            return
        if authorized_via_flag:
            authorization_source = 'get_preparation_change()'
        elif authorized_via_generation:
            authorization_source = 'kds_send_generation'
        elif authorized_via_direct_sale:
            authorization_source = 'Direct Sale sync_from_ui context (uuid match)'
        else:
            authorization_source = 'Table Send sync_from_ui context (single-order batch fallback)'
        _logger.info(
            "FlexSys KDS sync_from_ui: order #%s - genuine Send authorized via %s, "
            "triggering KDS sync.", order.id, authorization_source)
        # REAL BUG FIX ("SECOND CRITICAL ISSUE"): sync happens FIRST;
        # authorization marker(s) are only consumed/advanced AFTER it
        # completes without raising - see this method's own docstring
        # for the complete explanation. If _flexsys_kds_sync() itself
        # raises, this exception propagates up to
        # _flexsys_kds_process_sync_from_ui()'s own per-entry try/except
        # (isolating it from other orders in the same batch, unchanged
        # from the earlier fix for that), and - critically - neither
        # marker below is touched, so the NEXT sync_from_ui call for
        # this same order (whether an Odoo-level retry or the next
        # ordinary save) will correctly find this Send still pending
        # and retry it, rather than having silently lost it.
        order._flexsys_kds_sync(is_send_write=True)
        order.kds_preparation_change_requested = False
        if signature:
            order.kds_last_processed_send_signal = signature
        if authorized_via_generation:
            order.kds_last_processed_send_generation = incoming_generation

    def _flexsys_kds_cancel(self):
        """AUDIT FIX / NEW REQUIREMENT ("POS Cancellation Propagation",
        IMPORTANT): supporting pre-payment Send Triggers (kds_send_trigger
        on pos.config) introduced a real lifecycle gap - a POS order that
        already reached the kitchen and then gets cancelled used to leave
        its kds.order silently active forever, a ghost ticket still
        sitting in the production queue with nothing to signal what
        happened. Idempotent by construction: kds.order.action_cancel()
        checks the order isn't already in a terminal state before doing
        anything (via _wf_transition's own transition-matrix validation,
        backed up by the explicit early-return here), so calling this
        more than once on an already-cancelled/already-completed order is
        always a safe no-op - no duplicate events, no exception.

        Deliberately does NOT retroactively cancel an order that's
        already fully Completed by the time the POS side is cancelled
        (e.g. a very late POS-side correction after the food was already
        served) - preserves that production history rather than
        rewriting it, matching the same "completed work is never
        silently undone" principle used elsewhere (product-change
        reroute, action_cancel's own line-level filtering).
        """
        self.ensure_one()
        self = self.sudo()
        kds_order = self.kds_order_id
        if not kds_order or kds_order.state in ('cancelled', 'completed'):
            return
        kds_order.action_cancel(bypass_check=True)

    # ---------------------------------------------------------------
    # Point 3: this used to be create-once ("if kds_order_id: return").
    # It is now a real sync entry point: first call creates the KDS
    # order+lines, every later call (line added/changed/removed after
    # the ticket was already sent to the kitchen) runs a delta diff that
    # emits ADDED / UPDATED / REMOVED instead of resending the order.
    #
    # Real bug fixed here: this used to run as whichever user happened to
    # be ringing up the sale (the cashier), which meant the FlexSys KDS
    # station-assignment record rule (kds.access.mixin /
    # rule_kds_order_line_station) blocked order creation entirely for
    # any cashier not personally assigned to a kitchen station - which is
    # every cashier, since assigning cashiers to kitchen stations makes
    # no sense. This is automated system integration triggered by a POS
    # sale, not an interactive station worker's own action, so it now
    # runs as sudo() - deliberately bypassing both ir.model.access and
    # ir.rule for this call chain, the same way any other Odoo
    # integration hook (e.g. a stock move triggered by confirming a sale
    # order) runs with elevated rights rather than under the confirming
    # user's own permissions.
    # ---------------------------------------------------------------
    def _flexsys_kds_is_refund_order(self):
        """CRITICAL FIX (dev request "Runtime Regression Fix Package",
        BUG-06 - "the highest-risk issue discovered in this testing
        round"): a financial refund/return must NEVER create or affect a
        kitchen preparation ticket. Confirmed live: refunding 1 x Club
        Sandwich on an already-Completed order created a brand new KDS
        ticket showing "-1 x Club Sandwich" with an active START button
        - a refund was silently treated as a fresh order to prepare.

        Detected here, at the authoritative ingestion point
        (_flexsys_kds_sync() below), not hidden in the frontend - a
        refund order excluded here never enters _flexsys_kds_create()/
        _flexsys_kds_diff_lines() at all, so it can never touch SLA,
        station workload, printing, analytics, counters, realtime
        events, or audit interpretation, matching the request's own
        explicit list of what must not be affected.

        Two independent, defensively-written signals, since this
        project has repeatedly confirmed (see hooks.py's own docstring
        for the history) that exact field names on core Odoo models are
        not something to hardcode a single assumption about in this
        specific build:

        1. `refunded_orderline_id` on pos.order.line - the standard
           Odoo field marking a line as refunding an original line, if
           present on this build. Checked for existence first, never
           assumed.
        2. Fallback: every actual product line (types this module cares
           about - see _flexsys_kds_create_lines' own filter) has a
           negative quantity. A refund order's lines are negative by
           construction; a genuine new sale's are not - this holds
           regardless of what any refund-tracking field happens to be
           named on a given build, so it still catches a refund order
           correctly even if signal 1 doesn't apply.

        A single line with a positive/zero quantity found among actual
        product lines is enough to conclude "this is a normal order",
        even if some other line happens to be negative for an unrelated
        reason (a discount line, a rounding line) - deliberately
        conservative, since wrongly treating a genuine order as a
        refund (silently dropping real kitchen work) is a worse failure
        than the reverse.
        """
        self.ensure_one()
        product_lines = self.lines.filtered(
            lambda l: l.product_id.type in ('consu', 'product', 'service'))
        if not product_lines:
            return False
        if 'refunded_orderline_id' in product_lines._fields:
            if any(product_lines.mapped('refunded_orderline_id')):
                return True
        return all(l.qty < 0 for l in product_lines)

    def _flexsys_kds_reconcile_refund(self):
        """REAL BUG FIX ("Paid Order Refund Is Not Synchronized Back to
        the Original KDS Ticket", CRITICAL/HIGH), confirmed live: a
        partial refund (1 of 2) and a subsequent full refund (the
        remaining 1) on an already-PREPARING KDS ticket left it
        completely unchanged - still showing the full original quantity,
        still PREPARING, still offering READY, even once the entire paid
        quantity had been refunded. "This is incorrect and operationally
        dangerous."

        Required concept, implemented exactly as specified: for each
        refunded original line, `effective_kitchen_qty = original_qty -
        cumulative_refunded_qty` - cumulative and idempotent by
        construction, since it's recomputed fresh from ALL refund lines
        against that original line every time this runs (search, not a
        running counter), so processing the same or an overlapping set
        of refunds twice, or in any order, converges on the same correct
        answer rather than double-subtracting.

        Never creates a new KDS ticket or a negative production line -
        this method only ever reduces or cancels an EXISTING
        kds.order.line, matching the same authoritative-backend
        principle BUG-06 already established for excluding a refund
        order from ingestion in the first place.

        Correlation relies on `refunded_orderline_id` (checked for
        existence first, same defensive posture as
        _flexsys_kds_is_refund_order() above, for the same reason - see
        that method's own docstring) - without it, there is no reliable
        way to identify which original line a given refund line
        corresponds to, so that specific line is silently skipped rather
        than guessed at (matching this method's own "wrongly affecting a
        genuine order is worse than doing nothing" philosophy).

        Stage-specific behavior, exactly as specified:
        - effective_qty <= 0 (fully refunded): cancels the ORIGINAL
          kds.order.line through the real action_cancel() if it's still
          active (New/Preparing/Ready) - full audit trail, the same
          CANCELLED display treatment and retention every other
          cancellation in this module already has. A line already
          Completed is never force-cancelled (action_cancel() itself
          would raise for a Completed line anyway) - logged as a
          terminal, informational event only, per "If operational
          visibility is desired, use a terminal informational state/
          event only - never production work."
        - effective_qty > 0 but reduced, line still active (New/
          Preparing/Ready): quantity reduced in place, current STATE is
          never touched - "do not reopen unnecessary production" for a
          Ready line, and a Preparing line correctly stays Preparing.
          qty_delta accumulates the same way a normal POS quantity
          decrease already does (BUG-09's own established mechanism),
          so the reduction shows as "UPDATED (-1)" on both screens.
        - effective_qty > 0, line already Completed: never mutated -
          "the original completed work remains historically completed"
          (the same principle BUG-02B/BUG-10 already established) - a
          partial refund after completion is recorded as an
          informational event only, never a new production delta (a
          refund is a reduction, never new work to prepare).
        """
        for line in self.lines.filtered(
                lambda l: l.product_id.type in ('consu', 'product', 'service')):
            if 'refunded_orderline_id' not in line._fields:
                continue
            original_pos_line = line.refunded_orderline_id
            if not original_pos_line:
                continue
            kline = self.env['kds.order.line'].search([
                ('pos_order_line_id', '=', original_pos_line.id),
                ('state', '!=', 'cancelled'),
            ], limit=1, order='id desc')
            if not kline:
                continue
            all_refund_lines = self.env['pos.order.line'].search([
                ('refunded_orderline_id', '=', original_pos_line.id),
            ])
            cumulative_refunded = sum(abs(l.qty) for l in all_refund_lines)
            effective_qty = original_pos_line.qty - cumulative_refunded
            kds_order = kline.order_id

            if effective_qty <= 0:
                if kline.state == 'completed':
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s fully refunded after original line was already "
                               "completed - informational only, no production change")
                        % {'product': kline.product_name})
                else:
                    kline.action_cancel(
                        reason=_('Fully refunded in POS (refund order %s)') % (self.pos_reference or self.name),
                        bypass_check=True)
            elif effective_qty < kline.qty:
                if kline.state == 'completed':
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s partially refunded after original line was already "
                               "completed (qty %(old_qty)s -> %(new_qty)s) - informational only, "
                               "no production change")
                        % {'product': kline.product_name, 'old_qty': kline.qty, 'new_qty': effective_qty})
                else:
                    # REAL BUG FIX ("BUG-11 [fourth report] - Sequential
                    # qty_delta baseline is still wrong at runtime"):
                    # baseline is explicitly last_kds_sent_qty, not
                    # kline.qty - see that field's own docstring
                    # (kds_order_line.py) for the full explanation.
                    qty_decrease = effective_qty - kline.last_kds_sent_qty
                    old_qty = kline.qty
                    kline.write({
                        'qty': effective_qty,
                        'line_change': 'updated',
                        'qty_delta': qty_decrease,
                        'last_kds_sent_qty': effective_qty,
                    })
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s reduced by refund (qty %(old_qty)s -> "
                               "%(new_qty)s, refund order %(ref)s)")
                        % {'product': kline.product_name, 'old_qty': old_qty,
                           'new_qty': effective_qty, 'ref': self.pos_reference or self.name})
                    from .kds_notify import notify_station
                    notify_station(self.env, kline.station_id)
            # effective_qty >= kline.qty: nothing to reconcile (e.g. this
            # specific refund line/order was already fully accounted for
            # by an earlier pass - idempotent no-op).

    def _flexsys_kds_sync(self, is_send_write=False):
        self.ensure_one()
        self = self.sudo()
        # CRITICAL FIX (BUG-06, see _flexsys_kds_is_refund_order()'s own
        # docstring): checked first, before the send-trigger gate below
        # - a refund order must never reach _flexsys_kds_create()/
        # _flexsys_kds_diff_lines() under any trigger configuration.
        #
        # BUG-11 FIX ("Paid Order Refund Is Not Synchronized Back to the
        # Original KDS Ticket"), confirmed live: BUG-06 correctly stopped
        # a refund from creating its OWN new ticket, but stopped there -
        # the ORIGINAL ticket was never told anything had changed, so it
        # kept showing the full, un-refunded quantity indefinitely (a
        # fully-refunded order still showed "PREPARING" with an active
        # READY button - "operationally dangerous," per the report's own
        # words). _flexsys_kds_reconcile_refund() below closes that gap:
        # correlates the refund back to the ORIGINAL kds.order.line and
        # reduces/cancels it accordingly - never creating a second ticket
        # of its own, exactly the same "identify at the authoritative
        # ingestion point" principle BUG-06 already established.
        if self._flexsys_kds_is_refund_order():
            self._flexsys_kds_reconcile_refund()
            return
        # CHANGE REQUEST FIX ("POS Send-to-KDS Settings - Simplify and
        # Correct Triggers"), confirmed live: 'validation'/'submit' used
        # to trigger sync on ANY write touching 'lines'/'state' - which
        # is every edit at all (add/remove a product, change a qty,
        # simply re-saving the order) - "Adding products... Removing
        # products... Changing quantities... must NOT automatically
        # synchronize the order with KDS. The synchronization boundary
        # must be the cashier's explicit action: Send or New."
        #
        # 'send' mode now requires is_send_write=True - set by write()/
        # create() above via explicit Send-intent detection. Every OTHER write (add/remove/qty/attribute changes,
        # simply viewing or re-saving the order) leaves this False, so
        # it correctly accumulates with zero KDS sync until the next
        # genuine Send.
        #
        # REAL BUG FIX ("On Send to KDS Boundary Is Being Bypassed"),
        # confirmed live: this comment previously described the
        # trigger as "the vals being saved include
        # last_order_preparation_change" - mere presence, which turned
        # out to leak every single POS edit straight through, since
        # that field is part of nearly every save's own payload, not
        # exclusively a genuine Send. That detection logic now
        # checks the field's own JSON content for a non-empty
        # `metadata` key specifically - confirmed from Odoo 19's own
        # core source (_ensure_to_keep_last_preparation_change) to be
        # the actual distinguishing signal between a genuine
        # preparation-change event and an ordinary save that merely
        # carries the field along.
        #
        # Honest caveat, stated plainly rather than guessed past: the
        # `metadata`-key distinction itself is confirmed, from Odoo 19's
        # own core source, to be how the Preparation-Display-enabled
        # "Send" action's own write is distinguished from an ordinary
        # save (Scenario 1). Whether the "New" action (Scenario 2,
        # Preparation Display *disabled*) populates this same metadata
        # key has not been confirmed against a live instance - this
        # remains the one part of this change that still needs that
        # verification (see RELEASE_STATUS.md). Fails closed under this
        # uncertainty exactly as before: if "New" doesn't populate
        # metadata on a given build, orders under that configuration
        # simply never sync under 'send' mode, rather than syncing too
        # early.
        trigger = self.config_id.kds_send_trigger or 'payment'
        if trigger == 'payment':
            ready = self.state in ('paid', 'done', 'invoiced')
        else:
            # REAL BUG FIX ("Test Suite Reconciliation Round 2 +
            # Production Fix - Last POS Line Removal"), confirmed live:
            # `bool(self.lines)` alone meant an order whose LAST POS
            # line was deleted entirely (self.lines becomes empty)
            # failed this gate outright and never reached
            # _flexsys_kds_diff_lines() at all - even though that
            # method's own "line missing from current_ids" sweep
            # (below in this same file) is already fully equipped to
            # correctly cancel every remaining kds.order.line and log
            # a `line_removed` audit event for exactly this case, once
            # it's actually reached. Fixed by also allowing the gate
            # through when a kds_order_id already exists - an order
            # that was genuinely sent before, now with zero POS lines
            # left, must still reach reconciliation so its own
            # existing KDS ticket gets correctly cancelled, not
            # silently frozen showing stale, no-longer-real production.
            # An order that was NEVER sent before (no kds_order_id yet)
            # and has zero lines still correctly fails this gate either
            # way - `bool(self.lines) or bool(self.kds_order_id)` is
            # False for that case too, so an empty, never-sent order
            # still never creates a fresh, empty KDS ticket out of
            # nothing.
            ready = (
                is_send_write and self.state != 'cancel'
                and (bool(self.lines) or bool(self.kds_order_id))
            )
            # REAL BUG FIX ("Send / Re-Send Synchronization" - a stale-
            # code bug the client's own careful review of this exact
            # method found and fixed directly, confirmed correct here
            # and merged with full documentation), superseding the
            # v7.9.2-era comment this block used to carry: this line
            # used to overwrite kds_last_processed_send_signal with
            # self.last_order_preparation_change - the RAW field value,
            # including its own volatile metadata/serverDate (confirmed
            # in v7.9.7's own root-cause analysis to always change on
            # essentially every write). That made sense back when
            # kds_last_processed_send_signal was compared against that
            # same raw value directly (an earlier, now-removed approach,
            # now unused). Since v7.9.7's redesign, the field instead
            # holds a NORMALIZED, content-only signature (metadata
            # stripped - see _extract_preparation_content_signature()),
            # set exclusively by
            # _flexsys_kds_process_one_sync_from_ui_entry() BEFORE this
            # method is even called. This line was never removed when
            # that redesign happened - left in place, it immediately
            # overwrote the correct, just-set normalized signature with
            # the raw, metadata-carrying value on every single genuine
            # Send, corrupting the field for every comparison from that
            # point forward: the next sync_from_ui call's own normalized
            # signature could then never equal this now-raw value,
            # regardless of whether the order's own content had
            # genuinely changed or not - undermining the very
            # distinction this whole mechanism exists to make. Fixed by
            # simply no longer writing to this field here at all -
            # _flexsys_kds_process_one_sync_from_ui_entry() is now,
            # correctly, the field's own sole owner.
        if not ready:
            return
        if not self.kds_order_id:
            self._flexsys_kds_create()
        else:
            self._flexsys_kds_diff_lines()

    def _flexsys_kds_create(self):
        self.ensure_one()
        order_type = 'take_away' if getattr(self, 'takeaway', False) else 'dine_in'
        kds_order = self.env['kds.order'].create({
            'pos_order_id': self.id,
            'pos_config_id': self.config_id.id,
            'company_id': self.company_id.id,
            'source': 'pos',
            'order_type': order_type,
            'customer_name': self.partner_id.name or self.pos_reference or '',
            'note': _pos_note(self),
            # UI/DATA FIX ("FlexSys KDS - Master Change Request", item
            # 1, "Table Number - Fix"), confirmed live: kds.order's own
            # table_number field (models/kds_order.py) was defined but
            # never actually written to anywhere - it stayed empty for
            # every table order, no matter when it reached KDS. Fixed
            # here, at the exact same point every other kds.order field
            # is populated - this is the FIRST moment a POS order
            # becomes a kds.order at all, guaranteeing the table number
            # is present from the very first Send, before payment, not
            # only afterward (which is the confirmed requirement -
            # "لا يتم الاعتماد على POS Order النهائي فقط، لأن الطلب قد
            # يصل إلى KDS قبل الدفع").
            #
            # getattr(self, 'table_id', False) - not self.table_id
            # directly - matching this same method's own already-
            # established defensive pattern one line above
            # (getattr(self, 'takeaway', False)) for a field that only
            # exists at all when pos_restaurant is installed; a
            # Direct Sale order (no table - Odoo 19's own confirmed
            # "New Order" action) correctly has table_id unset, so
            # this naturally resolves to '' - "Direct Sale يبقى بدون
            # Table Number" is satisfied with no special-case branch
            # needed at all.
            #
            # table_id.table_number (an Integer) is used as the
            # primary source, not table_id.name - confirmed directly
            # from Odoo's own official forum that starting in Odoo 18,
            # "tables can only be numbered" (free-text table naming was
            # removed from core POS), making table_number the reliably
            # present, stable identifier across the Odoo 18/19 versions
            # this module actually targets. table_id.name is still
            # checked defensively first, purely as a fallback for any
            # environment where it happens to carry a genuinely useful,
            # distinct label - never assumed to exist or be meaningful.
            'table_number': _pos_table_number(self),
            # REAL BUG FIX ("BUG-14 - COMPLETED Retention Must Depend on
            # POS Closure"): under the 'payment' trigger, an order only
            # ever reaches KDS in the first place once it's ALREADY paid
            # - "reached KDS" and "POS closed" happen at the exact same
            # moment for that trigger mode, so pos.order.write()'s own
            # stamping logic (which only fires on a state *transition*,
            # requiring kds_order_id to already exist) would never catch
            # it - this order's kds_order_id doesn't exist until the
            # line right after this very create() call returns. Stamped
            # directly here instead, from self.state at the moment of
            # creation, for that specific trigger's own case; the 'send'
            # trigger's own orders (created while still genuinely
            # 'draft') correctly get None here, relying entirely on the
            # write()-time transition stamping for their own later
            # closure instead.
            'pos_closed_at': fields.Datetime.now() if self.state in ('paid', 'done', 'invoiced') else False,
        })
        self.kds_order_id = kds_order.id
        self._flexsys_kds_create_lines(self.lines)
        self._flexsys_kds_auto_print(kds_order)
        # REALTIME VALIDATION FIX (dev request, "Realtime Runtime
        # Validation" - "New order" was explicitly listed as one of the
        # scenarios to verify propagates without a manual refresh): this
        # method - the very first time a POS order gets sent to KDS -
        # never notified anyone. Every *later* change to an order (POS
        # Delta sync, workflow transitions, cancellation, reopen) already
        # does, via the shared _wf_transition path or an explicit call
        # at each site (see kds_order.py, kds_order_line.py,
        # kds_expeditor_task.py) - this was the one real gap: the single
        # most common, most important event (a brand new order arriving)
        # was relying entirely on the polling fallback to ever show up,
        # never actually pushed instantly. A brand-new order's lines
        # already have their station_id set by the routing engine inside
        # _flexsys_kds_create_lines (called just above), so this reads
        # that back rather than needing its own separate routing lookup.
        from .kds_notify import notify_stations
        notify_stations(self.env, kds_order.line_ids.mapped('station_id'))

    def _flexsys_kds_create_lines(self, pos_lines):
        line_vals = []
        for line in pos_lines:
            if line.product_id.type not in ('consu', 'product', 'service'):
                continue
            line_vals.append({
                'order_id': self.kds_order_id.id,
                'pos_order_line_id': line.id,
                'product_id': line.product_id.id,
                'qty': line.qty,
                'note': _pos_note(line),
                'variant_info': _pos_line_variant_info(line),
            })
        if line_vals:
            self.env['kds.order.line'].create(line_vals)

    def _flexsys_kds_diff_lines(self, decrease_only=False):
        """Delta-sync: compare current POS order lines against the
        kds.order.line records already routed to stations, and apply the
        minimal set of changes rather than recreating the ticket.

        - A POS line with no matching kds.order.line yet -> new kds line,
          line_change='added', routed fresh (may go to a station that
          hasn't seen this order at all yet).
        - A POS line whose product changed vs. its kds.order.line -> full
          re-route, not an in-place field update: the new product may
          belong to an entirely different station (e.g. Cappuccino/Coffee
          -> Chicken Burger/Kitchen), so this cancels the old line at its
          old station (or, if that line was already Completed/served,
          leaves that history alone and adds the new product as a fresh
          line instead) and creates a brand-new kds.order.line for the new
          product, which re-runs the routing engine from scratch. Both the
          old and new station get notified, and the new line's own
          auto-print rules apply normally the next time it's printed -
          there is no old print job to "convert", since kds.print.job
          records are an immutable log of what was actually sent to a
          printer, not something to retroactively edit.
        - A POS line whose qty/note changed (but not product) -> update in
          place, line_change='updated'. If it had already been marked
          Ready it is bumped back to New so the station notices.
        - A kds.order.line whose POS line is gone -> cancelled with
          line_change='removed', via the same action_cancel used for a
          manual cancel (so the same audit trail / SLA bookkeeping apply),
          but with bypass_check=True since this is a system-driven sync,
          not an interactive user action.
        """
        self.ensure_one()
        kds_order = self.kds_order_id
        # REAL BUG FIX ("POS Send-to-KDS Settings... redesign the
        # removal sync so it cannot leak early"), confirmed live: any
        # line flagged pending_removal by pos_order_line.py's own
        # unlink() (its POS line was deleted, but nothing about that was
        # made visible yet - see that method's own detailed comment, and
        # kds_order_line.py's pending_removal field docstring, for the
        # full explanation) is processed here, right at the START of
        # this method - the one place that only ever runs at the
        # correct sync boundary for whichever trigger mode is configured
        # (this method is never called except from _flexsys_kds_sync(),
        # which already gated on 'payment' state or the genuine Send/New
        # signal before ever reaching here). Applies the exact same
        # state-aware cancellation the old unlink()-time logic used to
        # apply immediately: a still-active line goes through the real,
        # audited action_cancel(); an already-Completed line uses
        # _system_cancel_after_completion() instead (see that method's
        # own docstring - action_cancel() itself explicitly refuses to
        # cancel a Completed line, correctly, for a real user-facing
        # cancel action, but a POS-driven removal after completion is a
        # different, system-driven scenario where marking it Cancelled
        # is the correct, intended outcome).
        # REAL BUG FIX (found during final review of "New Workflow
        # Integrity Issue - Unsent Removal Can Leave POS and KDS
        # Inconsistent"'s own decrease_only mechanism, before it had
        # ever actually been exercised by a test): this pending_removal
        # sweep used to run unconditionally, before any decrease_only
        # check - meaning the immediate decrease-only sync path
        # (pos_order_line.py's own write(), triggered purely by a
        # QUANTITY decrease on one line) would ALSO immediately cancel
        # any OTHER, completely unrelated line on the same order that
        # had been deleted outright (unlink()) but was still correctly
        # awaiting the next genuine Send/Payment - directly contradicting
        # the deliberate decision, documented in pos_order_line.py's own
        # unlink() (see its own detailed comment), NOT to extend
        # immediate sync to line deletion, only to quantity decreases.
        # Gated behind `not decrease_only` so the decrease-only path
        # touches only genuine quantity decreases, exactly as scoped;
        # the normal, full sync (decrease_only=False, the only way this
        # method was ever called before this feature existed) still
        # processes pending removals exactly as before - completely
        # unaffected.
        if not decrease_only:
            # BUG-05B FIX ("CI Still Red" report, Failure 5, second root
            # cause found beyond the earlier dead-code defect):
            # confirmed by direct tracing that this sweep processes each
            # pending_removal line INDIVIDUALLY, with no grouping by
            # pos_order_line_id at all - so by the time execution
            # reaches the separate active_lines_by_pos_line sweep
            # further below in this same method (which DOES correctly
            # group and log one CONSOLIDATED event), every line sharing
            # this pos_order_line_id has already been cancelled here,
            # individually, with no consolidated event - that later
            # sweep's own `l.state != 'cancelled'` filter then finds
            # nothing left to consolidate at all. Confirmed
            # mathematically before writing this fix: original(qty=4,
            # completed) + delta(qty=2, completed), both pending_removal
            # -> both cancelled individually right here, zero active
            # lines left for the later sweep to find.
            #
            # Fixed with the narrowest possible change: group by
            # pos_order_line_id first. A single-line group (by far the
            # most common case, and every existing test's own scenario)
            # goes through the EXACT SAME code, unchanged, as before -
            # zero behavioral difference. Only a genuine multi-line
            # group (more than one active kds.order.line sharing this
            # pos_order_line_id, all flagged pending_removal at once)
            # additionally logs one consolidated event afterward -
            # exactly matching the existing, established pattern the
            # active_lines_by_pos_line sweep below already uses.
            pending_removed = kds_order.line_ids.filtered('pending_removal')
            pending_groups = {}
            for kline in pending_removed:
                pending_groups.setdefault(kline.pos_order_line_id.id, []).append(kline)
            for pos_line_id, group in pending_groups.items():
                total_group_qty = sum(kl.qty for kl in group) if len(group) > 1 else None
                for kline in group:
                    if kline.state == 'completed':
                        kline._system_cancel_after_completion(
                            reason=_('Removed from POS order (was already completed)'))
                    elif kline.state != 'cancelled':
                        kline.action_cancel(reason=_('Removed from POS order after send'), bypass_check=True)
                    else:
                        kline.write({'pending_removal': False})
                if total_group_qty is not None:
                    self.env['kds.event'].log(
                        kds_order, event_type='line_removed', station=group[0].station_id,
                        note=_("%(product)s fully removed from POS order (quantity: "
                               "%(qty)s -> 0, cancelled_qty: %(qty)s)")
                        % {'product': group[0].product_name, 'qty': total_group_qty})
        # Only match against currently-active kds lines: a pos_order_line_id
        # can end up pointing at more than one kds.order.line over time (a
        # product-change reroute cancels the old one and creates a new one
        # sharing the same pos_order_line_id) - the cancelled one is closed
        # history, not something later diffs should match against.
        existing = {}
        for l in kds_order.line_ids:
            if l.pos_order_line_id and l.state != 'cancelled':
                existing[l.pos_order_line_id.id] = l
        current_ids = set()
        new_line_vals = []
        touched_stations = self.env['kds.station']

        for line in self.lines:
            if line.product_id.type not in ('consu', 'product', 'service'):
                continue
            current_ids.add(line.id)
            kline = existing.get(line.id)
            if kline:
                if kline.product_id != line.product_id:
                    touched_stations |= self._flexsys_kds_reroute_line(kds_order, kline, line)
                    continue
                # BUG-06 FIX ("Delta Reconciliation Recovery - Truth
                # Table Analysis"): confirmed by direct conceptual
                # analysis before writing this code, `changed` (used
                # below to gate entry into the `elif` branch for a
                # non-historical kline) used to compare kline.qty - a
                # STALE PARTIAL SHARE (this one line's own last-synced
                # quantity) - against line.qty - the FULL CURRENT POS
                # TOTAL. These are two different concepts colliding by
                # numeric coincidence whenever kline's own stale share
                # happens to equal the new total (exactly the failing
                # scenario: delta line's own last-synced qty was 2, POS
                # decreased 3->2, 2==2 by pure coincidence even though a
                # real change happened). The correct concept for "did
                # this specific line's own fair share genuinely change"
                # is: current POS total, minus every OTHER active
                # historical (ready/completed) sibling's own qty, minus
                # what THIS line was last confirmed to represent
                # (last_kds_sent_qty) - i.e. effective_qty (the same,
                # sibling-aware quantity elif's own body already
                # computes further below) compared against
                # kline.last_kds_sent_qty, not kline.qty against
                # line.qty directly. Computed once, early, here -
                # deliberately with different local variable names
                # (early_historical_siblings/early_effective_qty) from
                # elif's own separate, unmodified re-computation further
                # below, to avoid touching that already-working code at
                # all; this is purely a correction to what `changed`
                # itself measures.
                early_historical_siblings = kds_order.line_ids.filtered(
                    lambda l, pid=line.id, kid=kline.id: l.pos_order_line_id.id == pid
                    and l.id != kid and l.state in ('ready', 'completed'))
                early_effective_qty = line.qty - sum(early_historical_siblings.mapped('qty'))
                # REAL BUG FIX, confirmed at runtime (dev request
                # "Runtime Regression Fix Package", BUG-04, Case A):
                # a POS line whose qty was set to 0 used to fall through
                # to the generic "changed" branch below exactly like any
                # other qty adjustment, writing qty=0 and
                # line_change='updated' - the kitchen would see
                # "0 x Pasta Bolognese - UPDATED", not a clear signal
                # that the item was effectively removed. Operationally,
                # qty=0 on a previously-submitted item IS a removal - a
                # kitchen operator does not need to distinguish "the
                # customer no longer wants any of this" from "the line
                # was deleted outright" (handled separately, below the
                # main per-line loop, via the exact same action_cancel()
                # call this now shares). Routed through the same
                # authoritative cancellation path as every other
                # cancellation in this module - full audit trail
                # (previous state, timestamp, user, reason), the same
                # CANCELLED display treatment on both KDS screens, the
                # same grace-period retention - not a special-cased
                # silent removal.
                # BUG-05 FIX ("Delta Reconciliation Recovery Plan" -
                # the confirmed Root Cause for the original Problem 5),
                # confirmed by direct tracing before writing any code:
                # this branch used to only ever cancel `kline` - the one
                # line `existing` resolves to for this pos_order_line_id
                # - never the full set of active historical siblings
                # sharing the same id (an increase-after-Ready/Completed
                # that also matured to ready/completed, e.g.). A single
                # historical line was the only realistic case this
                # branch was ever exercised against before, so this
                # never surfaced until multiple historical siblings plus
                # a full zero-out were combined. Fixed by gathering
                # EVERY currently-active kds.order.line sharing this
                # pos_order_line_id (not just `kline`) and cancelling
                # each one through its own correct, state-appropriate
                # path - the same "gather every active sibling, not just
                # the `existing`-dict winner" principle already
                # established elsewhere in this same method for the
                # full-POS-line-removal case (see active_lines_by_pos_line
                # below) - plus one CONSOLIDATED audit event summarizing
                # the total zeroed-out quantity, matching that same
                # established pattern. Historical qty itself is never
                # rewritten - only state changes, exactly as before.
                if line.qty <= 0:
                    # Only cancel siblings this branch is actually
                    # authorized to touch: non-completed (cancellable
                    # via action_cancel unconditionally), or completed
                    # WHILE the POS order is still 'draft' (BUG-13's own
                    # rule, via _system_cancel_after_completion). A
                    # completed sibling with the POS order no longer
                    # 'draft' is deliberately EXCLUDED here, not merely
                    # skipped inside the loop - falling through to the
                    # normal `changed`/kline_is_historical logic just
                    # below instead, exactly as it already correctly did
                    # before this fix (that logic's own treat_as_frozen
                    # branch already handles "reduced to zero, POS order
                    # closed" correctly, informationally, with no state
                    # change) - this fix must never suppress that
                    # already-correct path for this specific sub-case.
                    zeroed_siblings = kds_order.line_ids.filtered(
                        lambda l, pid=line.id: l.pos_order_line_id.id == pid
                        and l.state not in ('cancelled',)
                        and not (l.state == 'completed' and self.state != 'draft'))
                    if zeroed_siblings:
                        total_zeroed_qty = sum(zeroed_siblings.mapped('qty'))
                        for sibling in zeroed_siblings:
                            if sibling.state == 'completed':
                                sibling._system_cancel_after_completion(
                                    reason=_('Quantity reduced to zero in POS while order still active'))
                            else:
                                sibling.action_cancel(
                                    reason=_('Quantity reduced to zero in POS'), bypass_check=True)
                            touched_stations |= sibling.station_id
                        # REAL BUG FIX ("Full CI Recovery" report,
                        # Failure 3 - Audit Trail on Qty -> 0),
                        # confirmed by direct tracing before writing
                        # this fix: this consolidated event used to be
                        # logged UNCONDITIONALLY, even for the single-
                        # sibling case (by far the most common
                        # scenario) - action_cancel()/
                        # _system_cancel_after_completion() above
                        # already log their OWN individual event, with
                        # meaningful old_value/new_value (e.g.
                        # 'preparing' -> 'cancelled'); the consolidated
                        # event carries neither (a summary has no single
                        # "old state" to report). Logged unconditionally,
                        # the consolidated event became the LATEST
                        # line_removed event for even a single-line
                        # zero-out, masking the real transition event
                        # from any query ordering by most-recent (e.g.
                        # `order='id desc', limit=1`) - reported
                        # directly: `old_value == False` instead of the
                        # real 'preparing'. Fixed with the same
                        # single-vs-multi distinction already
                        # established for the pending_removal sweep
                        # elsewhere in this method: only a genuine
                        # multi-sibling group additionally logs this
                        # summary - the single-sibling case now relies
                        # solely on its own line's own individual,
                        # meaningful event, exactly as before this
                        # whole zeroing-out feature's own multi-sibling
                        # support was added.
                        if len(zeroed_siblings) > 1:
                            self.env['kds.event'].log(
                                kds_order, event_type='line_removed', station=zeroed_siblings[0].station_id,
                                note=_("%(product)s reduced to zero in POS (quantity: %(qty)s -> 0, "
                                       "cancelled_qty: %(qty)s)")
                                % {'product': zeroed_siblings[0].product_name, 'qty': total_zeroed_qty})
                        continue
                    # zeroed_siblings is empty: every active sibling for
                    # this pos_order_line_id is a completed line whose
                    # POS order has already closed - nothing here is
                    # authorized to touch it. Deliberately falls through
                    # (no `continue`) to the normal reconciliation logic
                    # below, matching the exact behavior this exact
                    # sub-case already had before this fix.

                # BUG-06 FIX (continued from the comment above, right
                # after `kline` was resolved): `changed` now measures
                # the correct concept - "did this line's own fair
                # share, once every other historical sibling's own
                # share is subtracted first, genuinely change" - using
                # early_effective_qty/kline.last_kds_sent_qty (computed
                # above) instead of the old, coincidence-prone
                # kline.qty/line.qty direct comparison. note/variant
                # remain correct as a per-line comparison exactly as
                # before - unchanged.
                changed = (early_effective_qty != kline.last_kds_sent_qty) \
                    or (kline.note != _pos_note(line)) \
                    or (kline.variant_info != _pos_line_variant_info(line))
                # REAL BUG FIX, confirmed at runtime (dev request
                # "Remaining Fixes After v19.0.7.0.0 Review", item 2):
                # this used to require kline.state not in ('completed',
                # 'cancelled') for ANY modification to be processed at
                # all - meaning a qty/note/variant change on an already-
                # Completed line was silently ignored entirely, not just
                # left un-reset like a Ready line. Scenario A (a brand
                # new product added after Completed) already worked
                # correctly via create()'s own
                # _system_reopen_if_production_incomplete() call;
                # Scenario B (an EXISTING completed line modified) had no
                # equivalent path at all. Fixed using the exact same
                # established pattern _flexsys_kds_reroute_line() already
                # uses for a product change on a completed line just
                # below - the original completed kline is never mutated
                # (preserves "previous completion, previous timestamps"
                # exactly as required), a brand-new kds.order.line is
                # created carrying the SAME pos_order_line_id (so it
                # correctly takes over as what future diffs match against
                # - the `existing` dict at the top of this method already
                # keys on pos_order_line_id, last-write-wins, same as the
                # reroute case relies on), and
                # _system_reopen_if_production_incomplete() (called via
                # the new line's own create()) reopens the order to
                # 'preparing' - "the reopened preparation represents new
                # work, while the original completed work remains
                # historically auditable."
                # REAL BUG FIX, confirmed at runtime (dev report "BUG-10 -
                # READY order incorrectly resets to NEW after POS
                # quantity increase"): a Ready line whose qty/note/
                # variant changed used to get bumped fully back to 'new' -
                # destroying
                # the fact that the PREVIOUS quantity had already been
                # prepared. "1 prepared + UPDATED (+1)" incorrectly
                # became "2 new" - the whole line, previously-prepared
                # portion included, looked like it needed a fresh
                # production cycle from scratch, with an active START
                # button, even though only the +1 increase genuinely did.
                #
                # Fixed using the EXACT same established pattern already
                # used for a Completed line's own equivalent case just
                # below (kline.state == 'completed') - unified into one
                # shared branch, since the underlying requirement is
                # identical for both: "the previous prepared/ready
                # quantity stays preserved as completed/ready production
                # history... only the new delta needs a new production
                # cycle... must not lose or reset previous production
                # history." The original Ready line is never mutated -
                # keeps its own state, qty, ready_time, exactly as
                # before - and a brand-new delta line is created instead,
                # carrying the SAME pos_order_line_id so it correctly
                # takes over as what future diffs match against.
                #
                # REAL BUG FIX (found while fixing this, checking the
                # already-existing Completed-line branch below for the
                # same underlying issue - "make sure old tests are still
                # LOGICALLY correct, not just passing"): that branch's
                # own delta line used to carry qty=line.qty (the FULL NEW
                # POS total, e.g. 7 for a 5->7 change), not qty=2 (just
                # the increase) - silently double-counting the 5 already-
                # completed units against the new delta's own full 7,
                # exactly the "2 new" mistake this same dev report is
                # pointing at, just for Completed instead of Ready. Fixed
                # for both at once, consistently, below.
                # REAL BUG FIX ("FlexSys KDS – Bug Report: Quantity
                # decrease after READY is not reflected"), confirmed
                # live and traced to its exact root cause: once a PRIOR
                # increase-after-Ready created a separate delta line
                # (this branch's own increase handling below), and THAT
                # delta line has ALSO since reached ready/completed,
                # `existing` (built above, keyed purely by
                # pos_order_line_id) can only ever hold ONE
                # kds.order.line per POS line - the LAST one encountered
                # while iterating kds_order.line_ids (ordered by id
                # ascending, so the most recently CREATED sibling - i.e.
                # exactly the delta line, never the original). Every
                # comparison further below used to read `kline.qty`/
                # `kline.last_kds_sent_qty` - that ONE sibling's own
                # share alone - never the TRUE combined total already
                # shown to the kitchen for this product (original +
                # every later delta, summed). In the reported
                # reproduction (original=1 ready, delta=2 ready, true
                # total=3, POS decreases to 2), `kline` resolved to the
                # delta line alone (qty=2) - which, by pure coincidence,
                # already equaled the NEW POS quantity (2), so `changed`
                # (computed earlier purely from `kline.qty != line.qty`)
                # was already False, and the entire ready/completed
                # branch was never even entered - explaining exactly why
                # "KDS does not reflect the quantity decrease... no
                # cancellation/decrease delta is shown" - not a
                # coincidence limited to this one example, but the
                # general shape of the bug for ANY POS decrease that
                # lands on a value equal to the most recent sibling's
                # own share, or more generally any case where multiple
                # historical siblings sum to something `kline.qty` alone
                # doesn't reveal.
                #
                # Fixed by resolving the TRUE combined historical
                # quantity across every non-cancelled ready/completed
                # sibling sharing this same pos_order_line_id -
                # ready_siblings/total_historical_qty below - and using
                # THAT, not kline.qty/kline.last_kds_sent_qty alone, for
                # both detecting a genuine change and computing the real
                # delta. In the single-sibling case (no prior increase-
                # after-ready ever happened - every scenario every
                # earlier BUG-09/BUG-10/BUG-11/BUG-13 fix and their own
                # regression tests already cover), ready_siblings is
                # just {kline} and total_historical_qty == kline.qty
                # exactly as before - mathematically identical behavior,
                # confirmed by every one of those existing tests
                # continuing to pass unmodified. `changed` itself (used
                # by every OTHER branch below/elsewhere) is left
                # completely untouched - only entry into THIS specific
                # branch is widened, via an explicit OR, to also catch
                # the case `changed` alone coincidentally missed.
                kline_is_historical = kline.state in ('ready', 'completed')
                if kline_is_historical:
                    ready_siblings = kds_order.line_ids.filtered(
                        lambda l, pid=line.id: l.pos_order_line_id.id == pid
                        and l.state in ('ready', 'completed'))
                    total_historical_qty = sum(ready_siblings.mapped('qty'))
                else:
                    ready_siblings = self.env['kds.order.line']
                    total_historical_qty = 0.0

                # REAL BUG FIX ("Critical Bug Report - Send After
                # Immediate Decrease Reconciliation Re-Processes The
                # Same Change"), confirmed live: the outer `changed`
                # (computed once, at the very top of this loop, purely
                # from `kline.qty != line.qty`) compares only ONE
                # sibling's own PARTIAL share against the FULL POS
                # total - in the multi-sibling case this is almost
                # NEVER a meaningful "did anything really change"
                # signal, since a single sibling's own qty essentially
                # never equals the full POS line's own total by
                # construction, even when the TRUE combined total
                # already exactly matches it (the reported scenario:
                # after the new immediate decrease-reconciliation
                # feature - v7.26.0 - correctly settled the real total
                # at 2, `changed` still read True purely because
                # kline.qty, 1, != line.qty, 2, even though nothing
                # further actually needed to happen). Because this
                # branch's own entry condition still included `changed`
                # as one of its OR terms, a later, ordinary Send (the
                # normal, non-decrease-only, full sync) re-entered this
                # branch on a genuinely already-settled line, and its
                # own `qty_increment == 0` case then fell through to the
                # "note/variant-only change - re-confirm the whole
                # batch" logic below (deliberately using `line.qty`, the
                # FULL total, as the delta - correct ONLY for a genuine
                # note/variant change with no quantity change at all) -
                # silently fabricating a brand-new, phantom delta line
                # for the full current quantity even though nothing
                # about this product had actually changed since the
                # immediate reconciliation.
                #
                # Fixed at the reconciliation-state level, exactly as
                # required, not with a one-time "ignore next Send"
                # workaround: `changed` is no longer used as this
                # branch's own signal for "did quantity change" at all -
                # replaced by `qty_really_changed`, computed the same
                # correct way total_historical_qty already is (the TRUE
                # combined total against the current POS quantity, the
                # one authoritative comparison this entire method
                # already treats as ground truth everywhere else).
                # `note_variant_changed` is split out separately - it
                # remains a per-kline (not per-total) concept by nature
                # (note/variant describe THIS SPECIFIC line's own
                # current content, not an aggregate), so comparing it
                # against `kline` specifically is, and always was,
                # correct - only the QUANTITY half of the old combined
                # `changed` was ever the wrong comparison in the multi-
                # sibling case. Both immediate decrease reconciliation
                # (pos_order_line.py's own write(), decrease_only=True)
                # and the normal full Send/Payment sync
                # (decrease_only=False) now go through this exact same
                # qty_really_changed/total_historical_qty computation -
                # a single, authoritative reconciliation baseline, per
                # the request's own explicit "same core reconciliation
                # function/state" requirement - not two independent
                # quantity mechanisms.
                qty_really_changed = total_historical_qty != line.qty
                note_variant_changed = (kline.note != _pos_note(line)) \
                    or (kline.variant_info != _pos_line_variant_info(line))
                if kline_is_historical and (qty_really_changed or note_variant_changed):
                    # REAL BUG FIX ("BUG-13 - Quantity Changes After
                    # COMPLETED Are Ignored While POS Order Is Still
                    # Active"), confirmed live (KDS order 2629-3-000008,
                    # ICE TEA: POS qty 5 -> 3 while the KDS ticket was
                    # already COMPLETED and the POS order was still
                    # ACTIVE/OPEN - "POS correctly showed 3... KDS
                    # remained 5... no effective quantity reconciliation
                    # occurred"): "COMPLETED in KDS must NOT mean the POS
                    # order can no longer modify production data. As
                    # long as the corresponding POS order is still
                    # ACTIVE/OPEN, KDS must continue receiving and
                    # processing quantity increases, decreases, added
                    # products, removed products, product modifications"
                    # - a genuine, explicit business-rule change from
                    # every earlier round's own "Completed is always
                    # frozen/historical, never touched again" principle
                    # (BUG-02B/BUG-10/the "Change Request After BUG-11"
                    # item 2/the BUG-11 third+fourth reports), which was
                    # correct ONLY for the case this report distinguishes
                    # for the first time: a Completed ticket whose POS
                    # order has ALSO closed (paid/done/invoiced) - at
                    # that point the sale itself is settled and rewriting
                    # served history genuinely would be wrong. While the
                    # POS order remains 'draft' (still being actively
                    # managed - a dine-in table not yet billed), a
                    # Completed line is now reconciled exactly the same
                    # way a Ready line already correctly is: decrease
                    # reduces in place, increase creates a new delta
                    # line for only the additional amount, the original
                    # completed portion's own timestamps/history
                    # untouched either way.
                    #
                    # pos_still_active is computed once, from self.state
                    # (self IS the pos.order here) - 'draft' is Odoo's
                    # own core state for an order still being built/
                    # managed at the register (confirmed from Odoo 19's
                    # own addons/point_of_sale/models/pos_order.py:
                    # state Selection is draft/cancel/paid/done); a
                    # cancelled order's own lines are handled by
                    # _flexsys_kds_cancel() entirely separately and never
                    # reach this diff logic at all.
                    pos_still_active = self.state == 'draft'
                    # REAL BUG FIX (continued, same live report):
                    # treat_as_frozen must reflect whether ANY
                    # historical sibling is 'completed' while the POS
                    # order has closed - not just kline's own state -
                    # since a mixed history (e.g. original completed,
                    # a later delta still ready) sharing one
                    # pos_order_line_id must be treated consistently:
                    # once the sale itself has settled (POS order no
                    # longer draft), nothing about this product's own
                    # history should be rewritten regardless of which
                    # specific sibling `kline` happened to resolve to.
                    treat_as_frozen = (not pos_still_active) and any(
                        s.state == 'completed' for s in ready_siblings)
                    # REAL BUG FIX (continued): qty_increment is now
                    # computed against total_historical_qty (the TRUE
                    # combined total across every historical sibling),
                    # never kline.last_kds_sent_qty alone - see this
                    # branch's own opening comment above for the full
                    # root-cause explanation. In the single-sibling
                    # case this is exactly kline.last_kds_sent_qty as
                    # before (identical math, confirmed by every
                    # existing single-line test continuing to pass).
                    qty_increment = line.qty - total_historical_qty
                    if qty_increment <= 0 and qty_really_changed:
                        # REAL BUG FIX ("Change Request After BUG-11",
                        # item 2: "Quantity Decrease Delta - Display
                        # Negative Difference"), confirmed live: this
                        # used to ALWAYS just log-and-skip a decrease on
                        # a Ready/Completed line, for BOTH states alike -
                        # correct for a genuinely frozen Completed line
                        # ("the original completed work remains
                        # historically completed", never rewritten), but
                        # wrong for Ready: a genuine POS quantity
                        # decrease on a Ready line never actually reduced
                        # the line's own displayed quantity at all, and
                        # no delta/UPDATED(-N) showed.
                        #
                        # BUG-13 FIX: treat_as_frozen (computed above)
                        # now decides this, not kline.state directly - a
                        # Completed line only gets the frozen,
                        # informational-only treatment when its own POS
                        # order has ALSO closed; otherwise (Ready, or
                        # Completed with the POS order still active) it
                        # reduces in place exactly the same way, matching
                        # "do not reopen unnecessary production" (no
                        # delta line, no state change, no reset to New -
                        # just the quantity itself moving down) while
                        # correctly showing UPDATED (-N) via the same
                        # qty_delta mechanism BUG-09 already established.
                        if treat_as_frozen:
                            self.env['kds.event'].log(
                                kds_order, event_type='order_updated', station=kline.station_id,
                                note=_("%(product)s reduced after original line was already "
                                       "completed and the POS order closed (qty %(old_qty)s -> "
                                       "%(new_qty)s) - no new preparation delta created, "
                                       "completed history preserved")
                                % {'product': kline.product_name,
                                   'old_qty': total_historical_qty, 'new_qty': line.qty})
                        else:
                            # REAL BUG FIX ("FlexSys KDS – Bug Report:
                            # Quantity decrease after READY is not
                            # reflected"), the second, deeper defect
                            # found while fixing this: even once the
                            # branch above IS correctly entered, the
                            # previous write() here set `kline.qty =
                            # line.qty` directly - the FULL NEW POS
                            # TOTAL (2 in the reported example) written
                            # onto just ONE sibling's own qty. With a
                            # separate, untouched original sibling still
                            # showing its own 1, the real combined total
                            # after that write would have become 1 + 2 =
                            # 3 - the exact new POS quantity was 2, not
                            # 3, so this single-line write was already
                            # wrong the moment more than one historical
                            # sibling existed, entirely independent of
                            # the `changed`-detection defect above; it
                            # only ever looked correct in the pre-
                            # existing single-sibling tests because
                            # kline WAS the only historical line there,
                            # making kline.qty and total_historical_qty
                            # identical by construction.
                            #
                            # Fixed by distributing the REQUIRED
                            # decrease (total_historical_qty - line.qty)
                            # across ready_siblings from MOST RECENTLY
                            # CREATED to OLDEST (sorted by id descending)
                            # - "لا ينبغي تعديل أو إعادة فتح الكمية التي
                            # تم تجهيزها سابقًا" (the earliest/original
                            # prepared portion must not be reopened or
                            # modified) is honored by construction: the
                            # newest sibling (almost always `kline`
                            # itself, since it's what `existing` already
                            # resolved to) absorbs the decrease first,
                            # and only cascades into an OLDER sibling if
                            # the decrease genuinely exceeds what the
                            # newest one alone can give up - never
                            # touching the very original portion at all
                            # unless the customer's own new quantity is
                            # low enough to require it. A sibling
                            # reduced all the way to zero is cancelled
                            # outright (via the same authoritative
                            # action_cancel() every other zero-quantity
                            # case in this method already uses - full
                            # audit trail, same CANCELLED display
                            # treatment) rather than left showing a
                            # confusing "0 x" on the kitchen screen.
                            remaining_decrease = total_historical_qty - line.qty
                            for sibling in ready_siblings.sorted(key=lambda s: s.id, reverse=True):
                                if remaining_decrease <= 0:
                                    break
                                reducible = min(sibling.qty, remaining_decrease)
                                if reducible <= 0:
                                    continue
                                sib_old_qty = sibling.qty
                                sib_new_qty = sibling.qty - reducible
                                if sib_new_qty <= 0:
                                    sibling.action_cancel(
                                        reason=_('Quantity reduced in POS after this portion '
                                                 'was already %s') % sibling.state,
                                        bypass_check=True)
                                    self.env['kds.event'].log(
                                        kds_order, event_type='order_updated',
                                        station=sibling.station_id,
                                        note=_("%(product)s (qty %(old_qty)s, previously "
                                               "%(state)s) fully cancelled - POS quantity "
                                               "decrease absorbed this entire portion")
                                        % {'product': sibling.product_name, 'old_qty': sib_old_qty,
                                           'state': sibling.state})
                                else:
                                    sib_vals = {
                                        'qty': sib_new_qty,
                                        'line_change': 'updated',
                                        'qty_delta': -reducible,
                                        'last_kds_sent_qty': sib_new_qty,
                                    }
                                    # note/variant_info are only ever
                                    # meaningfully refreshed on the
                                    # sibling this exact POS line write
                                    # actually corresponds to (kline) -
                                    # an OLDER sibling absorbing overflow
                                    # from a cascade keeps its own
                                    # already-correct note/variant_info
                                    # completely untouched.
                                    if sibling.id == kline.id:
                                        sib_vals['note'] = _pos_note(line)
                                        sib_vals['variant_info'] = _pos_line_variant_info(line)
                                    sibling.write(sib_vals)
                                    self.env['kds.event'].log(
                                        kds_order, event_type='order_updated',
                                        station=sibling.station_id,
                                        note=_("%(product)s reduced after original line was "
                                               "already %(state)s (qty %(old_qty)s -> "
                                               "%(new_qty)s) - quantity reduced in place, no "
                                               "production reopened")
                                        % {'product': sibling.product_name, 'state': sibling.state,
                                           'old_qty': sib_old_qty, 'new_qty': sib_new_qty})
                                touched_stations |= sibling.station_id
                                remaining_decrease -= reducible
                            from .kds_notify import notify_station
                            notify_station(self.env, kline.station_id)
                        continue
                    # REAL FEATURE ("New Workflow Integrity Issue -
                    # Unsent Removal Can Leave POS and KDS
                    # Inconsistent"), the client's own explicit,
                    # deliberate choice: NOT frontend navigation
                    # blocking (rejected outright - "We do not want to
                    # block or warn the cashier, and we do not want to
                    # change the normal POS workflow") but immediate
                    # backend reconciliation specifically for
                    # DECREASES, regardless of the configured
                    # kds_send_trigger, while every other change
                    # (increases, new products) stays fully deferred to
                    # the next genuine Send/Payment exactly as before -
                    # see pos_order_line.py's own write() override for
                    # where this immediate path is actually invoked.
                    # decrease_only=True (that immediate path's own
                    # signal) reaching this point in the code means the
                    # branch above already determined qty_increment > 0
                    # (a genuine increase, not a decrease) - explicitly
                    # not what this call was meant to process, so it's
                    # skipped entirely rather than creating a delta line
                    # a decrease-only sync has no business creating.
                    if decrease_only:
                        continue
                    # Quantity genuinely increased: the delta line
                    # represents ONLY the increase (qty_increment), not
                    # the new full total - "1 prepared + 1 needed" stays
                    # visible as two separate, honest quantities, never
                    # silently inflating to "2 new". A note/variant-only
                    # change with qty unchanged (qty_increment == 0, but
                    # `changed` is still True) has no sensible partial-
                    # delta concept - the customer wants the *entire*
                    # already-prepared/ready batch reconfigured to the
                    # new spec, not just some of it, so the delta line
                    # carries the full current quantity in that specific
                    # sub-case only.
                    #
                    # BUG-13 FIX: an increase on a Completed line whose
                    # POS order has closed (treat_as_frozen) still falls
                    # through to here exactly as before - a delta line
                    # still gets created either way (an increase always
                    # means genuinely new work, regardless of whether the
                    # sale itself has settled), so no branching is needed
                    # for that specific case; only the log message below
                    # distinguishes it.
                    delta_qty = qty_increment if qty_increment > 0 else line.qty
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%(product)s modified after original line was already "
                               "%(state)s (qty %(old_qty)s -> %(new_qty)s) - added as a new "
                               "delta line instead of rewriting existing production history")
                        % {'product': kline.product_name, 'state': kline.state,
                           'old_qty': kline.qty, 'new_qty': line.qty})
                    new_delta_line = self.env['kds.order.line'].create({
                        'order_id': kds_order.id,
                        'pos_order_line_id': line.id,
                        'product_id': line.product_id.id,
                        'qty': delta_qty,
                        'note': _pos_note(line),
                        'variant_info': _pos_line_variant_info(line),
                        'line_change': 'updated',
                        # REAL BUG FIX ("Regression detected", 
                        # test_final_bugfix_client_example_1_to_3_after_
                        # ready_delta_is_2), confirmed live: qty_delta
                        # was never set explicitly on this brand-new
                        # delta line's own create() call - it silently
                        # kept the field's own default (0.0) instead of
                        # delta_qty, so the kitchen's own "UPDATED (+N)"
                        # display for this line would have shown +0
                        # instead of the actual increase. A pre-existing
                        # defect, not introduced by any recent change -
                        # only now surfaced because CI's own 5-failure
                        # halt was previously masking it behind other,
                        # unrelated failures. last_kds_sent_qty is
                        # already correctly set to this same value
                        # automatically by kds.order.line's own create()
                        # override (line.last_kds_sent_qty = line.qty) -
                        # only qty_delta itself was missing here.
                        'qty_delta': delta_qty,
                    })
                    touched_stations |= kline.station_id | new_delta_line.station_id
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=new_delta_line.station_id,
                        note=_("New preparation revision for %(product)s after %(state)s "
                               "original (delta qty %(qty)s)")
                        % {'product': new_delta_line.product_name, 'state': kline.state,
                           'qty': delta_qty})
                elif changed and kline.state != 'cancelled':
                    # AUDIT FIX ("POS Delta Sync Still Bypasses The
                    # Central Workflow", HIGH/FINAL BLOCKER): the plain
                    # data fields below (qty/note/variant/line_change)
                    # are legitimate direct writes - they're not in
                    # KDS_LINE_PROTECTED_FIELDS and never were the
                    # problem. A Ready line's own STATE is never reset
                    # here at all - it stays Ready, with a new delta
                    # line created separately instead (see the
                    # ready/completed branch above) - the only
                    # workflow-significant concern this fix addresses.
                    #
                    # REAL BUG FIX ("BUG-11 [third report, reusing the
                    # same client-side label as two earlier, different
                    # issues] - Sequential Quantity Delta Uses Wrong
                    # Baseline"), confirmed live: this used to accumulate
                    # qty_delta on top of whatever it already was
                    # (kline.qty_delta + this sync's own increment) -
                    # BUG-09's own original reasoning was that the
                    # kitchen should see the total change "since the
                    # previously ACKNOWLEDGED quantity", assuming that
                    # meant summing every unacknowledged sync's own delta
                    # together. That reasoning was wrong, and this report
                    # gives the precise counter-example: 2 -> 1
                    # (correctly UPDATED (-1)), then - with no
                    # acknowledgement in between - 1 -> 3 accumulated to
                    # UPDATED (+1) (-1 + 2), when the kitchen needed to
                    # see UPDATED (+2) - the change relative to the 1
                    # they were already shown, not some blend with a
                    # decrease that sync had already fully superseded.
                    # "Delta must always be calculated against the last
                    # successfully sent KDS quantity" - which is exactly
                    # what kline.qty already *is*, right before this
                    # write updates it again - qty_increment below (=
                    # effective_qty - kline.qty, i.e. new value minus the
                    # line's own current value) is already precisely
                    # that delta on its own, with no addition needed.
                    # Repeated changes before any acknowledgement now
                    # each independently show only their own most recent
                    # move (2->1 shows -1; then 1->3 shows +2; then 3->2
                    # would show -1) rather than an ever-growing blended
                    # total - matching this report's own worked example
                    # exactly, including its final "3 -> 2 = UPDATED
                    # (-1)" step.
                    #
                    # REAL BUG FIX (found while fixing "BUG-10 - READY
                    # order incorrectly resets to NEW after POS quantity
                    # increase", checking this branch for the same class
                    # of mistake per "make sure old tests are still
                    # LOGICALLY correct, not just passing"): kline
                    # reaching this branch might itself BE a delta line
                    # created by the new ready/completed branch above (on
                    # an EARLIER sync) - the `existing` dict at the top of
                    # this method keys purely on pos_order_line_id, so a
                    # delta line correctly takes over as what THIS sync
                    # matches against too, exactly as intended. But
                    # writing `line.qty` (the POS line's own full current
                    # total) directly into a delta line's own qty would
                    # silently lose the distinction the first sync
                    # deliberately created - e.g. 5 completed + delta of
                    # 2 (total POS qty 7), then POS changes to 10: without
                    # this fix, the delta line's own qty would jump to 10
                    # (the full new total) while the original completed
                    # line still separately shows 5 - implying 15 total
                    # when the real total is 10. Any historical (Ready/
                    # Completed) sibling line for the SAME pos_order_line_id
                    # is subtracted out first, so this line's own qty
                    # always represents only ITS OWN remaining share of
                    # the current total, matching the exact same "delta,
                    # not full total" principle applied above.
                    historical_siblings = kds_order.line_ids.filtered(
                        lambda l, pid=line.id, kid=kline.id: l.pos_order_line_id.id == pid
                        and l.id != kid and l.state in ('ready', 'completed'))
                    effective_qty = line.qty - sum(historical_siblings.mapped('qty'))
                    # REAL FEATURE (same client-decided approach as
                    # branch 1's own gate above): skip entirely unless
                    # this is a genuine decrease (effective_qty <
                    # kline.qty) - an increase or no-op reaching this
                    # exact branch under decrease_only=True is left
                    # completely untouched here, deferred to the next
                    # genuine Send/Payment exactly as before.
                    if decrease_only and effective_qty >= kline.qty:
                        continue
                    # REAL BUG FIX ("Regression detected after latest
                    # Delta fix", section 1, "Delta Sync Idempotency
                    # regression"), confirmed live: this branch's own
                    # entry condition above (`elif changed and
                    # kline.state != 'cancelled':`) uses the outer
                    # `changed` flag, computed from `kline.qty !=
                    # line.qty` - comparing THIS line's own partial
                    # share (kline.qty) against the FULL POS total
                    # (line.qty), exactly the same class of mistake
                    # already fixed for the ready/completed branch
                    # above (see qty_really_changed's own comment
                    # there) - but never applied here. Once a delta
                    # line exists for this pos_order_line_id (created
                    # by the ready/completed branch above, on an
                    # earlier sync) and becomes what `existing` here
                    # matches against, `changed` reads True on every
                    # subsequent call purely because kline.qty (this
                    # delta line's own partial share) almost never
                    # equals the full POS total by construction - even
                    # once effective_qty (the correct, sibling-
                    # subtracted comparison, computed just above) has
                    # already fully settled and genuinely nothing
                    # changed. With no guard here, that meant every
                    # repeated call re-executed the write() and logged
                    # a fresh audit event below, unconditionally -
                    # confirmed exactly matching the reported
                    # regression (5 -> 7 events across two additional,
                    # idempotent calls: one extra write+event each).
                    # Fixed with the one check actually missing: skip
                    # entirely, before any write or audit event, when
                    # effective_qty has already fully settled AND
                    # neither note nor variant genuinely changed either
                    # - the same "did anything real actually change"
                    # question qty_really_changed already answers
                    # correctly for the other branch, asked here too.
                    if (effective_qty == kline.last_kds_sent_qty
                            and kline.note == _pos_note(line)
                            and kline.variant_info == _pos_line_variant_info(line)):
                        continue
                    # BUG-02 FIX ("Delta Reconciliation Recovery Plan" -
                    # Sequential decrease reconciliation calculates the
                    # wrong remaining delta), confirmed by an actual
                    # multi-stage simulation before writing any code: 1
                    # READY -> 3 -> 2 -> 4 -> 1. `effective_qty` above
                    # can legitimately go NEGATIVE here - it means the
                    # required decrease exceeds THIS non-historical
                    # line's own full share alone and must cascade into
                    # historical_siblings (computed above) too, exactly
                    # as the main ready/completed branch's own separate,
                    # already-correct siblings.sorted() distribution
                    # already does for a purely-historical case - never
                    # reached by this branch before this fix. kline
                    # itself is fully cancelled first (its own entire
                    # share is genuinely gone), then the remaining
                    # shortfall cascades into historical_siblings,
                    # newest-first, via the small dedicated helper
                    # method above - never writes a negative qty.
                    if effective_qty < 0:
                        old_kline_qty = kline.qty
                        kline.action_cancel(
                            reason=_("Quantity reduced in POS below this line's own share"),
                            bypass_check=True)
                        touched_stations |= kline.station_id
                        self.env['kds.event'].log(
                            kds_order, event_type='order_updated', station=kline.station_id,
                            note=_("%(product)s (qty %(old_qty)s) fully cancelled - POS "
                                   "quantity decrease exceeded this line's own full share, "
                                   "cascading into earlier production history")
                            % {'product': kline.product_name, 'old_qty': old_kline_qty})
                        remaining_decrease = -effective_qty
                        sorted_siblings = historical_siblings.sorted(key=lambda s: s.id, reverse=True)
                        touched_stations |= self._flexsys_kds_distribute_decrease_over_siblings(
                            kds_order, sorted_siblings, remaining_decrease)
                        continue
                    # REAL BUG FIX ("BUG-11 [fourth report] - Sequential
                    # qty_delta baseline is still wrong at runtime"),
                    # confirmed STILL reproducing live even after the
                    # v7.7.3 fix that stopped accumulating qty_delta -
                    # this is the exact branch handling the report's own
                    # reproduction scenario (a 'preparing' line, the
                    # single most common case). v7.7.3's own fix used
                    # kline.qty itself as the implicit baseline
                    # (mathematically equivalent to what's required, in
                    # theory) - but the dev report explicitly asked to
                    # "verify which field/value is actually being used
                    # as the authoritative 'last sent quantity'" rather
                    # than trust that equivalence blindly. Switched to
                    # the explicit, dedicated last_kds_sent_qty field
                    # (kds_order_line.py - see its own docstring for the
                    # full contract) instead of kline.qty, and that same
                    # field is updated to the new value in this exact
                    # same write() call, immediately after being read -
                    # eliminating any possibility of a stale read
                    # between computing this sync's own delta and
                    # recording what the next sync's own baseline should
                    # be. Required acceptance sequence from the dev
                    # report's own worked example, now correct: 2->1 =
                    # -1, then 1->3 = +2 (not +1), then 3->2 = -1.
                    qty_increment = effective_qty - kline.last_kds_sent_qty

                    kline.write({
                        'qty': effective_qty,
                        'note': _pos_note(line),
                        'variant_info': _pos_line_variant_info(line),
                        'line_change': 'updated',
                        'qty_delta': qty_increment,
                        'last_kds_sent_qty': effective_qty,
                    })
                    touched_stations |= kline.station_id
                    self.env['kds.event'].log(
                        kds_order, event_type='order_updated', station=kline.station_id,
                        note=_("%s updated (qty/notes changed after send)") % line.product_id.display_name)
            else:
                # REAL FEATURE (same client-decided approach as both
                # gates above): a genuinely NEW product (no existing
                # kds.order.line for this pos_order_line_id at all) is
                # an addition, never a decrease - skipped entirely
                # under decrease_only=True, deferred to the next
                # genuine Send/Payment exactly as before.
                if decrease_only:
                    continue
                # BUG-03 FIX ("Delta Reconciliation Recovery Plan" -
                # Phantom zero line), confirmed by an actual identity
                # trace before writing any code: `existing` (built
                # above) deliberately excludes cancelled lines - correct
                # for its own stated purpose ("closed history, not
                # something later diffs should match against") - but a
                # POS line whose own qty was reduced to 0 (cancelled by
                # the qty<=0 branch on an earlier sync) is still
                # physically present in self.lines (only unlink()
                # removes it entirely) and so still reaches this exact
                # `else` branch on every LATER sync, with `kline`
                # resolving to None every time (its own real
                # kds.order.line still exists, but cancelled, invisible
                # to `existing` by design) - silently creating a brand-
                # new, phantom kds.order.line at qty=0 on every single
                # later sync, indistinguishable in the database from a
                # genuinely new product. Fixed with the one check
                # actually missing: a POS line at qty<=0 is never a
                # genuinely new addition - skip entirely. Deliberately
                # scoped to ONLY this branch (a line with no existing,
                # active kds.order.line at all) so a legitimate later
                # re-add (POS quantity later goes from 0 back to a
                # positive value) is completely unaffected - at that
                # point line.qty is positive again, so this check simply
                # doesn't apply, and the line is added normally.
                if line.qty <= 0:
                    continue
                new_line_vals.append({
                    'order_id': kds_order.id,
                    'pos_order_line_id': line.id,
                    'product_id': line.product_id.id,
                    'qty': line.qty,
                    'note': _pos_note(line),
                    'variant_info': _pos_line_variant_info(line),
                    'line_change': 'added',
                })

        if new_line_vals:
            new_lines = self.env['kds.order.line'].create(new_line_vals)
            touched_stations |= new_lines.mapped('station_id')
            for kline in new_lines:
                self.env['kds.event'].log(
                    kds_order, event_type='line_added', station=kline.station_id,
                    note=_("%s added after order was sent") % kline.product_name)

        # REAL BUG FIX ("KDS Full Line Removal / Quantity -> 0"),
        # confirmed live (5 -> 4 -> 6 -> complete the +2 delta -> 0: KDS
        # kept showing BOTH "4 x FLAT WHITE" and "2 x FLAT WHITE" after
        # the POS line was deleted entirely - "the synchronization/
        # reconciliation logic appears to process only lines that still
        # exist in the current POS snapshot... a line that existed
        # previously but is missing from the current snapshot is
        # therefore ignored"): the removal-detection loop below used to
        # iterate `existing.items()` - but `existing` is a dict keyed by
        # pos_order_line_id, and this exact scenario (original completed
        # line + a delta line from an earlier increase, BOTH
        # simultaneously active/non-cancelled, BOTH sharing the SAME
        # pos_order_line_id) is precisely the case `existing`'s own
        # "last write wins" construction (a few lines above) was never
        # meant to fully represent for THIS purpose - its own comment
        # already acknowledges "a pos_order_line_id CAN end up pointing
        # at more than one kds.order.line" (correctly, for forward-
        # matching future diffs against the most recent one), but a
        # dict can only ever hold ONE value per key, so only the LAST of
        # the two active lines ever appeared in `existing` at all - the
        # other was completely invisible to this loop, silently never
        # cancelled, no matter how many times sync ran.
        #
        # Fixed by grouping EVERY currently-active kds.order.line on
        # this order by its own pos_order_line_id (a real multi-value
        # grouping, not a dict that can only hold one) - every line
        # sharing a now-missing pos_order_line_id is found and cancelled
        # together, each through the correct state-appropriate path
        # (action_cancel() for a still-active line,
        # _system_cancel_after_completion() for one already Completed -
        # never a negative-quantity "work item", never new production,
        # matching "do not create a new preparation work item" and "do
        # not reopen the order to PREPARING merely because of the
        # cancellation" exactly - is_expeditor_ready naturally already
        # excludes cancelled lines, so an order whose every line just
        # became cancelled together correctly stays wherever it already
        # was). One additional, consolidated audit event is logged per
        # removed POS line summarizing the TOTAL cancelled quantity
        # across every one of its own kds.order.line records together
        # ("quantity: 6 -> 0, cancelled_qty: 6") - each individual
        # line's own cancellation still logs its own event too (via
        # action_cancel()/_system_cancel_after_completion() themselves),
        # so the full per-line history remains intact; this additional
        # event exists specifically to make the TOTAL immediately
        # legible without needing to sum several separate entries by
        # hand.
        #
        # Idempotent by construction, not by any extra bookkeeping: once
        # cancelled, every line permanently satisfies `l.state !=
        # 'cancelled'` as False, so it's simply absent from
        # `active_lines_by_pos_line` on every subsequent poll/sync -
        # nothing here can ever re-cancel the same line or log the same
        # event twice.
        # REAL BUG FIX (found during the same final review as the
        # pending_removal fix above): this loop must ALSO be gated
        # behind `not decrease_only` for the identical reason - a POS
        # line missing from current_ids means it was removed entirely
        # (unlink()), never a quantity decrease on a still-existing
        # line (that case is handled entirely by the branches above,
        # inside the main per-line loop). Without this gate, the
        # immediate decrease-only sync path (triggered purely by a
        # QUANTITY decrease on some OTHER, unrelated line on the same
        # order) would ALSO immediately cancel any fully-removed line
        # still correctly awaiting the next genuine Send/Payment -
        # exactly the same contradiction with pos_order_line.py's own
        # unlink()-time decision this method's own pending_removal
        # sweep was just fixed for, just reached via a different path
        # (a removed line whose own pending_removal flag hadn't been
        # picked up yet vs. one already reflected in current_ids
        # simply not containing its id).
        if not decrease_only:
            active_lines_by_pos_line = {}
            for l in kds_order.line_ids:
                if l.pos_order_line_id and l.state != 'cancelled':
                    active_lines_by_pos_line.setdefault(l.pos_order_line_id.id, []).append(l)
            for pos_line_id, klines in active_lines_by_pos_line.items():
                if pos_line_id in current_ids:
                    continue
                total_removed_qty = sum(kl.qty for kl in klines)
                for kline in klines:
                    if kline.state == 'completed':
                        kline._system_cancel_after_completion(
                            reason=_('Removed from POS order after the order was already completed'))
                    else:
                        kline.action_cancel(reason=_('Removed from POS order after send'), bypass_check=True)
                    touched_stations |= kline.station_id
                self.env['kds.event'].log(
                    kds_order, event_type='line_removed', station=klines[0].station_id,
                    note=_("%(product)s fully removed from POS order (quantity: %(qty)s -> 0, "
                           "cancelled_qty: %(qty)s)")
                    % {'product': klines[0].product_name, 'qty': total_removed_qty})

        # AUDIT FIX ("POS Delta Sync Still Bypasses The Central
        # Workflow", HIGH/FINAL BLOCKER): replaces the previous raw
        # `kds_order.write({'state': 'preparing'})`. Called
        # unconditionally - _system_reopen_if_production_incomplete()'s
        # own internal check is a cheap no-op unless the order is
        # actually sitting at Ready/Completed with production no longer
        # fully ready, so no need to replicate that condition here too.
        kds_order._system_reopen_if_production_incomplete(
            reason=_('POS order %s modified after send') % (self.pos_reference or self.name))

        from .kds_notify import notify_stations
        notify_stations(self.env, touched_stations)

    def _flexsys_kds_distribute_decrease_over_siblings(self, kds_order, siblings, remaining_decrease):
        """BUG-02 FIX ("Delta Reconciliation Recovery Plan" - Sequential
        decrease reconciliation calculates the wrong remaining delta),
        confirmed by an actual multi-stage simulation before writing
        any code: 1 READY -> 3 -> 2 -> 4 -> 1. At the final step,
        `existing` resolves to a still-'new' (non-historical) delta
        line whose own share alone (2) is smaller than the required
        decrease (3, from 4 down to 1) - the `elif` branch this helper
        is called from has no mechanism of its own to cascade the
        remainder into READY/COMPLETED siblings once the non-historical
        line's own full share is exhausted, unlike the main
        ready/completed branch just above it (which already handles
        this correctly for a purely-historical case via its own,
        separate, already-correct sorted-siblings distribution).
        Writing `effective_qty` directly in that case would silently
        write a NEGATIVE quantity onto a kds.order.line - never
        acceptable.

        This is a small, dedicated, elif-only helper - deliberately NOT
        a shared refactor of the main branch's own already-correct,
        already-tested distribution logic just above it in this same
        file, to avoid any risk of touching that proven-correct code
        path. Same distribution semantics though (newest-created sibling
        absorbs the decrease first, cascading into older ones only if
        genuinely needed - the earliest/original portion is never
        touched unless the decrease truly requires reaching into it),
        applied here to whichever siblings this call site passes in.

        `siblings` must be sorted newest-first by the caller (matches
        the main branch's own `ready_siblings.sorted(key=..., reverse=True)`
        convention). Mutates each sibling in place (cancels or reduces),
        logs one audit event per touched sibling, and returns the set of
        touched stations.
        """
        touched_stations = self.env['kds.station']
        for sibling in siblings:
            if remaining_decrease <= 0:
                break
            reducible = min(sibling.qty, remaining_decrease)
            if reducible <= 0:
                continue
            sib_old_qty = sibling.qty
            sib_new_qty = sibling.qty - reducible
            if sib_new_qty <= 0:
                sibling.action_cancel(
                    reason=_('Quantity reduced in POS, cascading into this historical '
                             'portion after the more recent line was fully absorbed'),
                    bypass_check=True)
                self.env['kds.event'].log(
                    kds_order, event_type='order_updated', station=sibling.station_id,
                    note=_("%(product)s (qty %(old_qty)s, previously %(state)s) fully "
                           "cancelled - POS quantity decrease cascaded into and absorbed "
                           "this entire portion")
                    % {'product': sibling.product_name, 'old_qty': sib_old_qty, 'state': sibling.state})
            else:
                sibling.write({
                    'qty': sib_new_qty,
                    'line_change': 'updated',
                    'qty_delta': -reducible,
                    'last_kds_sent_qty': sib_new_qty,
                })
                self.env['kds.event'].log(
                    kds_order, event_type='order_updated', station=sibling.station_id,
                    note=_("%(product)s reduced after original line was already "
                           "%(state)s (qty %(old_qty)s -> %(new_qty)s) - decrease cascaded "
                           "into this portion, no production reopened")
                    % {'product': sibling.product_name, 'state': sibling.state,
                       'old_qty': sib_old_qty, 'new_qty': sib_new_qty})
            touched_stations |= sibling.station_id
            remaining_decrease -= reducible
        return touched_stations

    def _flexsys_kds_reroute_line(self, kds_order, kline, pos_line):
        """Handle a POS line whose product_id changed after the ticket was
        already routed: this is not a field update, it's potentially a
        move to a completely different station, so it goes through
        cancel-old + create-new (which re-runs the routing engine) rather
        than mutating kline.product_id in place. Returns the set of
        stations that need a realtime refresh (old + new)."""
        old_station = kline.station_id
        if kline.state == 'completed':
            # Already served under the old product - don't rewrite served
            # history, just log the swap and add the new product as a
            # fresh line so the correct (possibly different) station sees
            # it as a new item to prepare.
            self.env['kds.event'].log(
                kds_order, event_type='order_updated', station=old_station,
                note=_("Product changed after original line was already completed "
                       "(%(old)s -> %(new)s) - added as a new line instead of rewriting history")
                % {'old': kline.product_name, 'new': pos_line.product_id.display_name})
        else:
            kline.action_cancel(
                reason=_('Product changed on POS line (re-routing)'), bypass_check=True)

        new_line = self.env['kds.order.line'].create({
            'order_id': kds_order.id,
            'pos_order_line_id': pos_line.id,
            'product_id': pos_line.product_id.id,
            'qty': pos_line.qty,
            'note': _pos_note(pos_line),
            'variant_info': _pos_line_variant_info(pos_line),
            'line_change': 'updated',
        })
        self.env['kds.event'].log(
            kds_order, event_type='order_updated', station=new_line.station_id,
            note=_("Product changed on line: now routed %(product)s -> %(station)s")
            % {'product': new_line.product_name,
               'station': new_line.station_id.name if new_line.station_id else _('UNROUTED')})
        return old_station | new_line.station_id

    def _flexsys_kds_auto_print(self, kds_order):
        for station in kds_order.station_ids:
            if not station.auto_print:
                continue
            # AUDIT FIX ("Auto Print Without a Valid Printer", MEDIUM):
            # this used to build printer_id from
            # `station.printer_ids.filtered('is_default')[:1] or
            # station.printer_ids[:1]` and pass it straight into create()
            # without checking whether either search actually found
            # anything - a station with Auto Print enabled but zero
            # printers configured got `printer_id: False` (an empty
            # recordset's .id), silently creating a permanently
            # unexecutable pending job that would sit in the queue
            # forever with no alert to anyone. Now explicitly checks
            # first and logs a clear configuration-error audit event
            # instead of creating the broken job.
            printer = station.printer_ids.filtered('is_default')[:1] or station.printer_ids[:1]
            if not printer:
                self.env['kds.event'].log(
                    kds_order, event_type='override', station=station,
                    note=_("CONFIGURATION ERROR: Auto Print is enabled for station "
                           "'%s' but it has no printer configured - no print job "
                           "was created. Add a printer to this station or disable "
                           "Auto Print.") % station.name
                )
                continue
            self.env['kds.print.job'].create({
                'order_id': kds_order.id,
                'station_id': station.id,
                'printer_id': printer.id,
                'job_type': 'auto',
                'scope': 'station_items',
            })
