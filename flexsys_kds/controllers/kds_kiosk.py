# -*- coding: utf-8 -*-
"""
Public kiosk access - no Odoo login required.

Security model: possession of the per-station `kiosk_token` (see
kds.station.kiosk_token) IS the credential, in place of a logged-in
user. Every route here re-validates the token against the requested
station on every call (constant-time comparison), and the JSON API
surface is deliberately narrow:
- Only this station's own orders/lines are ever returned (the token is
  scoped to exactly one station's `code`, checked again server-side on
  every line action so a valid token for Station A can't be used to
  touch a line that actually belongs to Station B by guessing IDs).
- Only 'accept' / 'start' / 'ready' / 'complete' (all line-level -
  'complete' was order-level when first added in v5.4, alongside the
  manual-Complete design reversal, but became line-level in BUG-07's
  station-scoped completion work; see kds_order_line.py's own
  action_complete()) are allowed actions. No cancel, no reprint, no
  reopen, no cross-station move - anything requiring Supervisor+
  judgement stays behind a real Odoo login in the backend, on purpose.
  'complete' fits this same Operator-tier bar
  (ACTION_MIN_GROUP['complete']) - it's not a Supervisor-only move. A
  leaked kiosk URL should be able to do no more damage than "mark a
  food item as further along than it should be, or mark an already-
  Ready order as picked up", never "cancel a paying customer's order"
  or "see every station".

The HTML page itself is deliberately plain server-rendered HTML/CSS/JS
with no dependency on Odoo's frontend framework (Owl, the webclient
service registry, etc.) - those all assume an authenticated backend
session to bootstrap, which a public page by definition doesn't have.
This trades some code reuse with the authenticated KDS screen for
guaranteed-correct behavior with zero dependency on this Odoo 19 build's
frontend internals (several of which have already turned out to differ
from stock Odoo elsewhere in this module).
"""
import hmac
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

# UX DECISION - see controllers/kds.py's own COMPLETED_GRACE_MINUTES for
# the full rationale, including the dev request this specific value (5
# minutes) traces back to. Kept in sync with that constant manually
# (no shared config source exists yet - see that same comment on why
# this stays a plain constant for now).
COMPLETED_GRACE_MINUTES = 5
# See controllers/kds.py's own CANCELLED_GRACE_MINUTES for the full
# rationale (dev request "Cancellation Visibility Improvement"). Kept in
# sync manually, same as COMPLETED_GRACE_MINUTES above.
CANCELLED_GRACE_MINUTES = 5


def _effective_stage(lines):
    """BUG-10 FIX - see controllers/kds.py's own matching, more detailed
    docstring for the full explanation. Kept in sync manually, same as
    COMPLETED_GRACE_MINUTES/CANCELLED_GRACE_MINUTES above.

    REAL BUG FIX ("CANCELLED FILTER CLASSIFICATION + RETENTION
    LIFECYCLE", Issue 1) - see controllers/kds.py's own matching, more
    detailed docstring for the full explanation: a fully-cancelled
    station now returns the distinct 'cancelled' value, not a BUG-08
    "preserved last stage" value - this is what actually fixes "NEW = 6"
    with all 6 cards genuinely CANCELLED.
    """
    active = [l for l in lines if l.state != 'cancelled']
    if not active:
        return 'cancelled' if lines else 'new'
    if all(l.state == 'completed' for l in active):
        return 'completed'
    if all(l.state in ('ready', 'completed') for l in active):
        return 'ready'
    if any(l.state in ('preparing', 'ready', 'completed') for l in active):
        return 'preparing'
    return 'new'


def _station_from_token(env, station_code, token):
    if not station_code or not token:
        return None
    station = env['kds.station'].sudo().search([
        ('code', '=', station_code), ('active', '=', True),
    ], limit=1)
    if not station or not station.kiosk_token or not hmac.compare_digest(station.kiosk_token, token):
        return None
    return station


class FlexSysKdsKioskController(http.Controller):

    @http.route('/flexsyskds/public/<string:station_code>/<string:token>',
                type='http', auth='public', website=False)
    def kiosk_page(self, station_code, token, **kwargs):
        env = request.env
        station = _station_from_token(env, station_code, token)
        if not station:
            return request.not_found()
        # "Branch" is sourced from the station's linked pos.config(s) - the
        # POS location name staff actually recognize - rather than the
        # legal company name, which is now shown separately instead.
        branch_name = ', '.join(station.pos_config_ids.mapped('name')) or ''
        html = _KIOSK_HTML_TEMPLATE % {
            'station_name': station.name,
            'branch_name': branch_name,
            'company_name': station.company_id.name or '',
            'station_code': station.code,
            'token': token,
        }
        return request.make_response(html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route('/flexsyskds/public/api/orders', type='jsonrpc', auth='public', csrf=False)
    def kiosk_orders(self, station_code, token):
        env = request.env
        station = _station_from_token(env, station_code, token)
        if not station:
            return {'ok': False, 'error': 'Invalid or expired kiosk link'}

        # UX DECISION (see COMPLETED_GRACE_MINUTES/CANCELLED_GRACE_MINUTES
        # above): a line shows on screen if it's genuinely active (not
        # completed, not cancelled), OR it's terminal (completed or
        # cancelled) but still within its OWN grace window.
        #
        # BUG-08 FIX ("Cancelled Lines Break Station Card Lifecycle /
        # Terminal Cleanup") - see controllers/kds.py's own matching,
        # more detailed comment for the full root-cause explanation:
        # this used to key the completed-line grace check off
        # order_id.completion_time (only ever set once EVERY station on
        # the order has completed), with an "or unset" fallback meaning
        # a completed line on a still-active multi-station order was
        # shown indefinitely. completed_at (kds_order_line.py, per-line,
        # stamped by this line's own action_complete()) is this
        # station's own completion timestamp, independent of any other
        # station on the same order.
        #
        # REAL BUG FIX ("Retention Must Follow POS Order Lifecycle") -
        # see controllers/kds.py's own matching, more detailed comment
        # for the full explanation: extends the same pos_closed_at gate
        # to Cancelled too - "this rule applies regardless of the
        # current KDS terminal state, including COMPLETED [and]
        # CANCELLED." Also gated on order_id.pos_order_id being set at
        # all - see controllers/kds.py's own matching comment for the
        # full explanation of why a ticket with no linked POS order must
        # fall back to its own completed_at/cancelled_at directly,
        # rather than unintentionally never expiring.
        pos_closed_cutoff = fields.Datetime.now() - timedelta(minutes=COMPLETED_GRACE_MINUTES)
        cancelled_cutoff = fields.Datetime.now() - timedelta(minutes=CANCELLED_GRACE_MINUTES)
        lines = env['kds.order.line'].sudo().search([
            ('station_id', '=', station.id),
            '|', '|',
                ('state', 'not in', ('completed', 'cancelled')),
                '&', ('state', '=', 'completed'),
                    '|',
                        '&', ('order_id.pos_order_id', '!=', False),
                            '|', ('order_id.pos_closed_at', '=', False), ('order_id.pos_closed_at', '>=', pos_closed_cutoff),
                        '&', ('order_id.pos_order_id', '=', False), ('completed_at', '>=', pos_closed_cutoff),
                '&', ('state', '=', 'cancelled'),
                    '|',
                        '&', ('order_id.pos_order_id', '!=', False),
                            '|', ('order_id.pos_closed_at', '=', False), ('order_id.pos_closed_at', '>=', cancelled_cutoff),
                        '&', ('order_id.pos_order_id', '=', False), ('cancelled_at', '>=', cancelled_cutoff),
        ])
        orders = lines.mapped('order_id').sorted(
            key=lambda o: (o.priority != 'vip', o.priority != 'urgent',
                            o.priority != 'priority', o.created_time))

        order_fg = env['kds.order'].sudo().fields_get(['order_type', 'priority', 'state'])
        line_fg = env['kds.order.line'].sudo().fields_get(['line_change'])
        order_type_labels = dict(order_fg['order_type']['selection'])
        priority_labels = dict(order_fg['priority']['selection'])
        state_labels = dict(order_fg['state']['selection'])
        line_change_labels = dict(line_fg['line_change']['selection'])

        result = []
        for order in orders:
            # REAL BUG FIX, confirmed live (dev request "Remaining Fixes
            # After v19.0.7.0.0 Review", item 1) - see controllers/
            # kds.py's own detailed comment for the full explanation.
            # Same fix here: `display_lines` (payload - terminal-but-
            # within-grace lines included) split from `active_line_sla`
            # (still correctly excludes cancelled - not a meaningful SLA
            # input).
            # BUG-08 FIX - see controllers/kds.py's own matching, more
            # detailed comment for the full explanation. Mirrors the
            # search domain's own completed_at/cancelled_at grace-period
            # conditions exactly, symmetrically for both terminal states.
            # BUG-14 FIX: order.pos_closed_at (not completed_at) anchors
            # a completed line's own grace check - see controllers/
            # kds.py's own matching comment for the full explanation.
            # REAL BUG FIX ("Retention Must Follow POS Order Lifecycle"):
            # order.pos_closed_at now also gates cancelled_at, exactly
            # the same way it already gates completed_at - and both are
            # themselves conditioned on order_id.pos_order_id being set
            # (see controllers/kds.py's own matching comment).
            display_lines = order.line_ids.filtered(
                lambda l, sid=station.id, cc=cancelled_cutoff, pcc=pos_closed_cutoff, o=order: l.station_id.id == sid and (
                    (l.state not in ('completed', 'cancelled'))
                    or (l.state == 'completed' and (
                        (o.pos_order_id and (not o.pos_closed_at or o.pos_closed_at >= pcc))
                        or (not o.pos_order_id and l.completed_at and l.completed_at >= pcc)
                    ))
                    or (l.state == 'cancelled' and (
                        (o.pos_order_id and (not o.pos_closed_at or o.pos_closed_at >= cc))
                        or (not o.pos_order_id and l.cancelled_at and l.cancelled_at >= cc)
                    ))
                ))
            if not display_lines:
                continue
            # Same fix as the backend controller: order.sla_status is
            # store=True and only recomputes on an explicit dependency
            # write, not purely from elapsed time - recompute live from
            # the (non-stored, always-fresh) line-level sla_status values
            # instead of trusting the potentially-stale stored field.
            active_line_sla = display_lines.filtered(lambda l: l.state != 'cancelled').mapped('sla_status')
            if 'late' in active_line_sla:
                live_sla_status = 'late'
            elif 'warning' in active_line_sla:
                live_sla_status = 'warning'
            else:
                live_sla_status = 'normal'
            pos_order = order.pos_order_id
            employee_name = ''
            pos_ref = ''
            table_label = ''
            if pos_order:
                employee_name = getattr(pos_order.sudo().user_id, 'name', '') or ''
                pos_ref = getattr(pos_order, 'pos_reference', '') or ''
                # Best-effort, defensive: restaurant.table field names
                # (table_id, floor_id, table_number vs. name) haven't been
                # verifiable against this specific Odoo 19 build without
                # live access - if the Restaurant module isn't installed
                # or uses different field names here, this just stays
                # blank and the chip is hidden client-side, it won't error.
                table = getattr(pos_order, 'table_id', False)
                if table:
                    floor_name = getattr(getattr(table, 'floor_id', False), 'name', '') or ''
                    table_num = getattr(table, 'table_number', '') or getattr(table, 'name', '') or ''
                    table_label = f"{floor_name} / {table_num}" if floor_name and table_num else (table_num or floor_name)
            result.append({
                'id': order.id,
                'name': order.name,
                'order_type_label': order_type_labels.get(order.order_type, order.order_type),
                'priority': order.priority,
                'priority_label': priority_labels.get(order.priority, order.priority),
                'state': order.state,
                'state_label': state_labels.get(order.state, order.state),
                # BUG-10 FIX: see controllers/kds.py's own matching,
                # more detailed comment.
                'effective_stage': _effective_stage(display_lines),
                'sla_status': live_sla_status,
                'customer_name': order.customer_name,
                'employee_name': employee_name,
                'pos_reference': pos_ref,
                'table_label': table_label,
                'created_time': order.created_time and order.created_time.isoformat() + 'Z',
                'lines': [{
                    'id': l.id,
                    'product_name': l.product_name,
                    'qty': l.qty,
                    'note': l.note,
                    'variant_info': l.variant_info,
                    'state': l.state,
                    'line_change': l.line_change,
                    'line_change_label': line_change_labels.get(l.line_change, l.line_change),
                    'qty_delta': l.qty_delta,
                    # BUG-08 FIX ("Preserve Last Operational State") - see
                    # controllers/kds.py's own matching, more detailed
                    # comment for the full explanation.
                    'preparation_start_time': l.preparation_start_time and l.preparation_start_time.isoformat() + 'Z',
                    'ready_time': l.ready_time and l.ready_time.isoformat() + 'Z',
                } for l in display_lines],
            })

        return {
            'ok': True,
            'station_name': station.name,
            'branch_name': station.company_id.name or '',
            'orders': result,
            'printing_enabled': station.operating_mode != 'kds_only',
            'stats': {
                'orders_count': len(result),
                'avg_prep_time': round(station.avg_prep_time, 1),
                'late_count': station.late_order_count,
            },
        }

    @http.route('/flexsyskds/public/api/action', type='jsonrpc', auth='public', csrf=False)
    def kiosk_action(self, station_code, token, line_id, action):
        env = request.env
        station = _station_from_token(env, station_code, token)
        if not station:
            return {'ok': False, 'error': 'Invalid or expired kiosk link'}
        # BUG-07 FIX ("Station COMPLETE does not transition from READY"):
        # 'complete' added here as a line-level action, replacing the
        # old order-level kiosk_order_complete() route below (removed -
        # superseded by this, see that route's own removal note) - see
        # kds_order_line.py's own new action_complete() for the full
        # explanation of what completing a single line now does,
        # independently of every other station on the same order.
        if action not in ('accept', 'start', 'ready', 'complete'):
            return {'ok': False, 'error': 'Action not available on the public kiosk'}

        line = env['kds.order.line'].sudo().browse(line_id).exists()
        if not line or line.station_id != station:
            # Deliberately generic: don't reveal whether the line exists
            # at all if it doesn't belong to this token's station.
            return {'ok': False, 'error': 'Line not found for this station'}

        method = {'accept': line.action_accept, 'start': line.action_start,
                  'ready': line.action_ready, 'complete': line.action_complete}[action]
        # REAL BUG FIX, found via a proactive sweep for hidden
        # regressions (not a reported failure): this route had NO
        # exception handling at all - every workflow action method has
        # always raised UserError for an invalid transition, and BUG-07's
        # own action_complete() guard made that significantly more
        # likely to be hit in practice on this exact endpoint (any
        # attempt to complete a station whose lines aren't actually all
        # Ready yet). Uncaught, this would have crashed with a raw,
        # unhandled server error - on a PUBLIC, unauthenticated kiosk
        # endpoint - instead of the clean {'ok': False, 'error': ...}
        # response the kiosk's own frontend JS already expects and
        # displays gracefully to the operator.
        try:
            method(bypass_check=True)
        except UserError as e:
            return {'ok': False, 'error': str(e)}
        return {'ok': True, 'state': line.state}

    # BUG-07 FIX ("Station COMPLETE does not transition from READY"):
    # kiosk_order_complete() (the order-level Complete endpoint added in
    # v5.4) removed - completing the whole order regardless of station
    # was exactly the bug: Kitchen completing would either fail (order
    # not yet 'ready' if another station hadn't caught up) or complete
    # every station's lines simultaneously (once it was), never "just
    # Kitchen's own portion". Superseded entirely by kiosk_action()
    # above now supporting a line-level 'complete' action - the frontend
    # calls that instead, once per line on this station's own card, same
    # as it already does for 'start'/'ready'.

    @http.route('/flexsyskds/public/api/print', type='jsonrpc', auth='public', csrf=False)
    def kiosk_print(self, station_code, token, order_id):
        env = request.env
        station = _station_from_token(env, station_code, token)
        if not station:
            return {'ok': False, 'error': 'Invalid or expired kiosk link'}
        if station.operating_mode == 'kds_only':
            return {'ok': False, 'error': 'Printing is not enabled for this station'}

        order = env['kds.order'].sudo().browse(order_id).exists()
        if not order or station not in order.station_ids:
            return {'ok': False, 'error': 'Order not found for this station'}

        # Same explicit decision as the backend controller: gated by the
        # station's printing configuration, not a user permission tier -
        # there's no logged-in user on the public kiosk to gate by
        # anyway, so bypass_check=True here matches every other kiosk
        # action (accept/start/ready).
        # UI/DATA FIX ("Printing Cleanup & Job History - Final
        # Request"), item 3: create_reprint() now raises a UserError
        # (NoPrinterConfiguredError specifically) instead of silently
        # creating a job with no printer, for a station with none
        # configured - this call had no try/except around it at all
        # before this fix, so that exception would have surfaced as an
        # unhandled server error instead of the clean {'ok': False,
        # 'error': ...} JSON response every other route on this kiosk
        # controller already returns for an expected failure.
        # error_code, when present, lets a kiosk frontend distinguish
        # this specific condition without pattern-matching the
        # translated message text - the same convention already
        # established in controllers/kds.py's own _kds_error().
        try:
            job = env['kds.print.job'].create_reprint(
                order, station, reason='kitchen_request', bypass_check=True)
        except UserError as e:
            result = {'ok': False, 'error': str(e)}
            error_code = getattr(e, 'error_code', None)
            if error_code:
                result['error_code'] = error_code
            return result
        return {'ok': True, 'job_id': job.id}


_KIOSK_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>FlexSys KDS - %(station_name)s</title>
<style>
  :root{
    --fs-blue:#1E88E5; --fs-orange:#FF9800; --fs-bg:#12161c; --fs-card:#1b212b;
    --fs-late:#ef4444; --fs-warning:#f59e0b; --fs-ready:#22c55e; --fs-muted:#7c8aa0;
  }
  /* REAL FIX (reported live: "touch on the card feels delayed"): the
     classic mobile-browser tap-delay - up to ~300ms while the browser
     waits to see whether a tap is actually the start of a double-tap-
     to-zoom gesture. The <meta viewport> tag above already sets
     user-scalable=no, which *should* disable this in most modern
     browsers on its own, but that's not consistently honored across
     every browser/OS combination a kitchen touch device might be
     running - explicit touch-action is the direct, reliable fix
     regardless of that. Applied universally (this is a touch-first
     kiosk with no pinch/double-tap-zoom use case at all, matching the
     viewport tag's own intent) rather than per-element, so nothing new
     added later accidentally reintroduces the delay by missing it. */
  *{box-sizing:border-box; touch-action:manipulation;} html,body{margin:0;padding:0;height:100%%;}
  body{
    background:var(--fs-bg); color:#eef2f7; font-family:'Segoe UI',Tahoma,sans-serif;
    overflow:hidden; transition:background .2s;
  }
  /* Light mode (toggle button in header): only the page/grid background
     changes to a light gradient - header, filters, and cards deliberately
     keep their existing dark styling, per request. */
  body.light-theme{
    background:linear-gradient(180deg, #eaf1f6 0%%, #dbe7ef 100%%);
  }
  body.light-theme .empty{ color:#5a6b7a; }
  .theme-toggle{
    background:#161c25; border:1px solid #202834; border-radius:50%%;
    width:34px; height:34px; display:flex; align-items:center; justify-content:center;
    cursor:pointer; padding:0;
  }
  .theme-toggle svg{ width:18px; height:18px; stroke:#aab6c8; }
  body.light-theme .theme-toggle{ background:#fff; border-color:#c7d6e0; }
  body.light-theme .theme-toggle svg{ stroke:#3a4a58; }
  .header{
    display:flex; justify-content:space-between; align-items:center;
    padding:10px 18px; background:#0a0e14; border-bottom:1px solid #1a212b;
  }
  .header-left{ display:flex; align-items:center; gap:14px; }
  .logo{ font-weight:800; font-size:18px; }
  .logo b{ color:var(--fs-blue); }
  .station-badge{
    background:var(--fs-blue); color:#fff; font-weight:700; font-size:13px;
    padding:6px 14px; border-radius:8px;
  }
  .header-info{ display:flex; gap:18px; font-size:11.5px; color:var(--fs-muted); }
  .header-info b{ color:#eef2f7; font-size:12.5px; display:block; }
  .company-badge{
    border:1px solid #2a3340; border-radius:8px; padding:7px 18px;
    font-size:13px; font-weight:700; color:#cfd8e6;
  }
  body.light-theme .company-badge{ border-color:#c7d6e0; color:#3a4a58; }
  .header-right{ display:flex; align-items:center; gap:16px; }
  .conn{ font-size:12px; color:var(--fs-muted); font-family:monospace; }
  .dot{ display:inline-block; width:7px; height:7px; border-radius:50%%; margin-inline-end:5px; }
  .dot-on{ background:var(--fs-ready); } .dot-off{ background:var(--fs-late); }
  .filters{ display:flex; gap:12px; padding:14px 18px; background:#0d1219; border-bottom:1px solid #161c25; }
  .fbtn{
    background:#161c25; color:#aab6c8; border:1px solid #232b37; padding:14px 26px;
    border-radius:12px; font-weight:800; font-size:20px; cursor:pointer;
    box-shadow:0 3px 8px rgba(0,0,0,.3); display:flex; align-items:center; gap:10px;
  }
  .fbtn .fcount{
    background:rgba(255,255,255,.12); padding:2px 10px; border-radius:8px; font-size:17px;
  }
  .fbtn.active{ background:var(--fs-blue); color:#fff; border-color:var(--fs-blue); }
  .fbtn.active .fcount{ background:rgba(255,255,255,.25); }
  body.light-theme .fbtn{ background:#fff; color:#3a4a58; border-color:#c7d6e0; }
  body.light-theme .fbtn .fcount{ background:rgba(0,0,0,.06); }
  .grid{
    /* Card width tightened to the requested preferred range (was capped
       at 420px, now 380px - still comfortably above the 320px minimum,
       fits more columns on a Full HD screen). justify-content:start
       still packs used tracks together (see the detailed comment kept
       below from the previous round's fix). */
    height:calc(100vh - 180px); overflow-y:auto; display:grid;
    grid-template-columns:repeat(auto-fit, minmax(320px,380px)); gap:14px; padding:14px 18px;
    /* HIGH-DENSITY LAYOUT (dev request, point 2: "card height should
       primarily follow its actual content... should NOT be forced to
       occupy a large fixed height"): CSS Grid items default to
       align-items:stretch, meaning every card in a row is silently
       force-stretched to match the TALLEST card in that same row - a
       1-item order sitting next to a 10-item order would get pulled
       tall to match it, pushing its own action button far below its
       actual content with a large empty gap in between. align-items:
       start overrides that default so each card sizes to its own
       natural content height instead, independent of its row-mates. */
    align-content:start; justify-content:start; justify-items:start; align-items:start;
  }
  .card{
    background:#fff; border-radius:14px; overflow:hidden;
    display:flex; flex-direction:column; position:relative;
    box-shadow:0 4px 14px rgba(0,0,0,.35);
    width:100%%; max-width:380px;
    /* HIGH-DENSITY LAYOUT (dev request, point 5: "a single order may
       contain many products... do not allow one very large order to
       destroy the entire grid layout... define a reasonable maximum
       visible card height... keep the header visible, keep the action
       area accessible, allow the product section to scroll"):
       max-height caps how tall any one card can ever get (roughly
       enough for ~6-7 line items at this font size before it starts
       scrolling internally instead of growing further - tall enough
       that the common case, a handful of items, never scrolls at all).
       Header (.card-head) and footer (.card-footer, the action button)
       sit OUTSIDE the scrollable region below (flex-shrink:0 on both),
       so they stay visible and reachable even for a 10+ item order -
       only .card-body (the line items) scrolls internally. */
    max-height:640px;
  }
  .card.celebrate{ animation:cardCelebrate .7s ease-in-out; z-index:5; }
  @keyframes cardCelebrate{
    0%%{ transform:rotate(0deg) scale(1); }
    50%%{ transform:rotate(200deg) scale(1.05); }
    100%%{ transform:rotate(360deg) scale(1); }
  }
  .card-head{
    background:var(--fs-blue); color:#fff; padding:16px;
    /* High-density layout: never shrunk or scrolled - always visible,
       even when .card-body below is internally scrolling. */
    flex-shrink:0;
  }
  .card.late .card-head{ background:var(--fs-late); }
  .card.warning .card-head, .card.priority .card-head{ background:var(--fs-orange); }
  .card.ready .card-head{ background:var(--fs-ready); }
  /* CANCELLATION VISIBILITY (dev request, point 2: "the operator must
     immediately understand that the entire order has been cancelled"):
     deliberately muted grey rather than red/late's alert color - this
     isn't an urgent problem needing attention, it's a completed
     non-event (nothing left to prepare), and reusing the "late/warning"
     alert color here would wrongly suggest otherwise. opacity on the
     whole card reinforces "this is over, not active" at a glance,
     matching how a fully cancelled order needs no interaction at all
     (see mainAction() - action is null, no button renders). */
  .card.cancelled{ opacity:.7; }
  .card.cancelled .card-head{ background:#5a6472; }
  .card-title-row{ display:flex; align-items:flex-start; gap:10px; }
  .accent-bar{ width:4px; height:34px; background:rgba(255,255,255,.55); border-radius:2px; flex-shrink:0; }
  .order-no{ font-size:28px; font-weight:800; line-height:1; }
  .ordered-ref{ font-size:11px; opacity:.75; margin-top:4px; font-family:monospace; }
  .chips-row{ display:flex; gap:7px; margin-top:12px; flex-wrap:wrap; }
  .chip{
    background:rgba(255,255,255,.95); color:#1a2330; font-size:11.5px; font-weight:700;
    padding:6px 11px; border-radius:8px; display:inline-flex; align-items:center; gap:5px;
  }
  .chip svg{ width:13px; height:13px; flex-shrink:0; }
  .chip-timer{ color:var(--fs-blue); }
  .card.late .chip-timer{ color:var(--fs-late); }
  .card.warning .chip-timer, .card.priority .chip-timer{ color:var(--fs-orange); }
  .card.ready .chip-timer{ color:var(--fs-ready); }
  .chip-timer.pulse{ animation:pulseTimer 1.6s ease-in-out infinite; }
  @keyframes pulseTimer{ 0%%,100%%{ opacity:1; } 50%%{ opacity:.5; } }
  .employee-row{
    margin-top:10px; font-size:12.5px; color:rgba(255,255,255,.9);
    display:flex; justify-content:flex-end; align-items:center; gap:6px;
  }
  .employee-row svg{ width:15px; height:15px; }
  .customer-name{
    font-size:13px; font-weight:800; color:#fff; background:rgba(255,255,255,.18);
    padding:4px 10px; border-radius:7px; display:inline-block; margin-top:8px;
  }
  .ribbon{
    position:absolute; top:10px; right:10px; background:rgba(0,0,0,.25); color:#fff;
    font-size:9.5px; font-weight:800; padding:3px 9px; border-radius:6px; z-index:1;
  }
  .status-blink{
    display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:800;
    letter-spacing:.5px; margin-top:10px; color:#fff;
  }
  .status-blink .dot{
    width:8px; height:8px; border-radius:50%%; background:#fff;
    animation:statusBlink 1.1s ease-in-out infinite;
  }
  @keyframes statusBlink{ 0%%,100%%{ opacity:1; } 50%%{ opacity:.15; } }
  /* HIGH-DENSITY LAYOUT (dev request, point 5): this is the section that
     scrolls internally once .card hits its own max-height (above) -
     min-height:0 is the essential flexbox override here (a flex child's
     default min-height:auto would otherwise refuse to shrink below its
     content's natural size no matter how constrained the parent is,
     silently defeating overflow-y:auto and just growing the card past
     its max-height instead). flex:1 1 auto lets it claim exactly the
     leftover space between the fixed-size header and footer. */
  .card-body{ padding:2px 16px; flex:1 1 auto; min-height:0; overflow-y:auto; }
  .line-item{ display:flex; align-items:flex-start; gap:12px; padding:13px 0; border-bottom:1px solid #eef1f4; }
  .line-item:last-child{ border-bottom:none; }
  .line-checkbox{
    width:21px; height:21px; border:2px solid #cbd3da; border-radius:6px; flex-shrink:0;
    margin-top:2px; display:flex; align-items:center; justify-content:center; cursor:pointer;
    background:#fff;
  }
  .line-checkbox.checked{ background:var(--fs-ready); border-color:var(--fs-ready); }
  .line-checkbox.in-progress{ background:var(--fs-blue); border-color:var(--fs-blue); }
  .line-checkbox svg{ width:13px; height:13px; stroke:#fff; display:none; }
  .line-checkbox.checked svg.icon-check{ display:block; }
  .line-checkbox.in-progress svg.icon-dash{ display:block; }
  /* CANCELLATION VISIBILITY (dev request, point 1: "visually
     distinguishable from active preparation lines"): cursor:default (not
     pointer) since a cancelled line's checkbox is display-only, no
     onclick handler attached at all (see the cancelled-line branch in
     the linesHtml map above). */
  .line-checkbox-cancelled{
    background:#8a94a3; border-color:#8a94a3; cursor:default;
  }
  .line-checkbox-cancelled svg{ width:13px; height:13px; stroke:#fff; display:block; }
  .line-item.line-cancelled{ opacity:.65; }
  .line-item.line-cancelled .line-title{ text-decoration:line-through; color:#7c8aa0; }
  .line-badge-cancelled{
    background:var(--fs-late) !important;
  }
  .line-main{ flex:1; min-width:0; }
  .line-title-row{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .line-title{ font-weight:800; font-size:15px; color:#1a2330; }
  .variant-pill{
    background:#fdecd2; color:#8a5a12; font-size:11.5px; font-weight:700;
    padding:3px 10px; border-radius:999px;
  }
  .line-note-row{ display:flex; align-items:center; gap:6px; margin-top:4px; font-size:12px; color:#8a94a3; }
  .line-note-row svg{ width:13px; height:13px; flex-shrink:0; }
  .line-badge{
    font-size:9.5px; background:var(--fs-blue); color:#fff; padding:2px 8px;
    border-radius:5px; font-weight:800; text-transform:uppercase;
  }
  .line-qty{ font-weight:800; font-size:15px; color:#1a2330; white-space:nowrap; }
  .card-footer{
    padding:14px 16px; display:flex; justify-content:space-between; align-items:center;
    /* High-density layout: never shrunk or scrolled - the action button
       stays reachable even for a 10+ item order (dev request, point 5:
       "keep the action area accessible"). */
    flex-shrink:0;
    border-top:1px solid #eef1f4; gap:10px;
  }
  .print-act{
    background:#fff; border:1px solid #d4dae1; border-radius:10px; width:44px; height:44px;
    display:inline-flex; align-items:center; justify-content:center; cursor:pointer;
    color:#556270; flex-shrink:0;
  }
  .print-act svg{ width:18px; height:18px; }
  .print-act:disabled{ cursor:not-allowed; opacity:.4; }
  .main-act{
    background:var(--fs-blue); color:#fff; border:none; border-radius:10px; padding:12px 30px;
    font-weight:800; font-size:15px; cursor:pointer; display:inline-flex; align-items:center; gap:8px;
  }
  .main-act svg{ width:16px; height:16px; }
  .card.late .main-act{ background:var(--fs-late); }
  .card.warning .main-act, .card.priority .main-act{ background:var(--fs-orange); color:#3a1f00; }
  .card.ready .main-act{ background:var(--fs-ready); }
  .empty{ grid-column:1/-1; text-align:center; padding:60px; color:var(--fs-muted); }
  .statbar{
    display:flex; justify-content:space-between; align-items:center;
    padding:8px 18px; background:#0a0e14; border-top:1px solid #1a212b;
    font-size:11.5px; color:var(--fs-muted); font-family:monospace;
  }
  .statbar b{ color:#eef2f7; }
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <span class="logo">FlexSys <b>KDS</b></span>
    <span class="station-badge">%(station_name)s</span>
    <div class="header-info">
      <div>Branch<b id="branchName">%(branch_name)s</b></div>
      <div>Time<b id="clock">--:--</b></div>
    </div>
  </div>
  <div class="company-badge" id="companyBadge">%(company_name)s</div>
  <div class="header-right">
    <button class="theme-toggle" id="fullscreenToggle" onclick="toggleFullscreen()" aria-label="Toggle fullscreen"></button>
    <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()" aria-label="Toggle light/dark mode"></button>
    <div class="conn"><span class="dot dot-on" id="dot"></span><span id="connLabel">Online</span></div>
  </div>
</div>
<div class="filters" id="filters"></div>
<div class="grid" id="grid"></div>
<div class="statbar">
  <span>Orders <b id="statOrders">0</b> &nbsp; Avg. Prep <b id="statAvg">--</b> min &nbsp; Late <b id="statLate">0</b></span>
  <span>KIOSK-%(station_code)s</span>
</div>

<script>
const STATION_CODE = %(station_code)r;
const TOKEN = %(token)r;
let ORDERS = [];
let FILTER = 'all';
let PRINTING_ENABLED = false;
let WAS_READY = new Set(); // order ids that were fully-Ready as of the last poll
let CELEBRATE_IDS = new Set(); // order ids that just NOW became fully-Ready this poll
let KNOWN_ORDER_IDS = null; // null until first load completes, so we never beep on page load
// CANCELLATION VISIBILITY (dev request, point 5): tracks which *lines*
// (not orders - a single item can be cancelled without its order being
// cancelled at all) were already cancelled as of the last poll, so the
// alert plays only for genuinely new cancellations, not every poll for
// as long as a cancelled line stays visible in its own grace window -
// same null-until-first-load pattern as KNOWN_ORDER_IDS above, for the
// same reason (never alert for cancellations already on screen when the
// page opens).
let KNOWN_CANCELLED_LINE_IDS = null;
// REALTIME VALIDATION (dev request, "no duplicate orders or transitions
// may occur because Bus + polling both receive the same event"): the
// kiosk has no Bus subscription at all (plain 4-second polling only -
// see setInterval(loadOrders, 4000) below), so the specific "two
// mechanisms racing" scenario doesn't apply here the way it does on the
// backend screen (see kds_store.js's own loadOrdersSeq for that case).
// The same underlying race class still exists though: if any one fetch
// ever takes longer than 4 seconds (network stress), the next poll
// fires anyway before the previous one resolves, and the two responses
// could resolve out of order - the later-resolving one would overwrite
// ORDERS with a slightly staler snapshot. Same sequence-number guard,
// same fix.
let loadOrdersSeq = 0;

// Web Audio API beep - generated in-code, no external sound file, so this
// keeps working even if the device is offline/the asset can't load.
// Browsers block audio until a user gesture happens on the page at least
// once (autoplay policy) - resumeAudioOnFirstInteraction() below handles
// that as best as JS can, but the very first order of the day may not
// audibly beep if literally nobody has tapped the screen yet. That's a
// browser platform limitation, not something fixable from here.
let AUDIO_CTX = null;
function getAudioContext() {
  if (!AUDIO_CTX) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) AUDIO_CTX = new Ctx();
  }
  return AUDIO_CTX;
}
function resumeAudioOnFirstInteraction() {
  const ctx = getAudioContext();
  if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
}
document.addEventListener('click', resumeAudioOnFirstInteraction, {once: true});
document.addEventListener('touchstart', resumeAudioOnFirstInteraction, {once: true});

function playBeep() {
  const ctx = getAudioContext();
  if (!ctx) return;
  try {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.value = 880;
    const now = ctx.currentTime;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.35, now + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
    osc.start(now);
    osc.stop(now + 0.36);
  } catch (e) { /* audio unavailable/blocked - fail silently, never break the screen over this */ }
}

// CANCELLATION VISIBILITY (dev request, point 5: "use a clearly
// distinguishable cancellation notification/sound so kitchen staff
// notice it quickly"): a lower-pitched double-tone, deliberately the
// opposite shape of playBeep() above (one bright rising tone) - two
// short, low, descending pulses read as "stop/attention" rather than
// "something arrived", so staff can tell the two apart without looking
// at the screen first.
function playCancelAlert() {
  const ctx = getAudioContext();
  if (!ctx) return;
  try {
    const now = ctx.currentTime;
    [[420, 0], [330, 0.16]].forEach(([freq, delay]) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'square';
      osc.frequency.value = freq;
      const start = now + delay;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(0.28, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.15);
      osc.start(start);
      osc.stop(start + 0.16);
    });
  } catch (e) { /* audio unavailable/blocked - fail silently, never break the screen over this */ }
}

function tickClock() {
  const d = new Date();
  document.getElementById('clock').textContent =
    d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
}
setInterval(tickClock, 1000); tickClock();

const THEME_KEY = 'flexsys_kds_theme_%(station_code)s';
const ICON_SUN = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path></svg>';
const ICON_MOON = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';
function applyTheme(theme) {
  document.body.classList.toggle('light-theme', theme === 'light');
  // Icon shows the mode you'd SWITCH TO (sun while dark = tap for light).
  document.getElementById('themeToggle').innerHTML = theme === 'light' ? ICON_MOON : ICON_SUN;
  try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}
}
function toggleTheme() {
  const current = document.body.classList.contains('light-theme') ? 'light' : 'dark';
  applyTheme(current === 'light' ? 'dark' : 'light');
}
let savedTheme = 'dark';
try { savedTheme = localStorage.getItem(THEME_KEY) || 'dark'; } catch (e) {}
applyTheme(savedTheme);

// KDS FULLSCREEN MODE (dev request "V1 Finalization", item 1, "Required
// for V1"): the standard browser Fullscreen API - requestFullscreen()/
// exitFullscreen() are purely a rendering-level browser feature, never
// reloading the page or touching any JS state, which is exactly why
// this satisfies every one of the request's "must NOT" requirements
// (no refresh, no lost filters/realtime/timers/ticket state, no
// duplicate orders) automatically, by construction, rather than
// needing special-case handling for each one - nothing about ORDERS,
// FILTER, the polling interval, or any other in-memory state is
// affected by entering/leaving fullscreen at all.
const ICON_EXPAND = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path></svg>';
const ICON_COMPRESS = '<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"></path></svg>';
function updateFullscreenIcon() {
  const btn = document.getElementById('fullscreenToggle');
  if (!btn) return;
  const isFullscreen = Boolean(document.fullscreenElement);
  // Icon shows the action a tap performs next (compress = currently
  // fullscreen, tap to exit; expand = currently windowed, tap to enter)
  // - same "show what happens next" convention as the theme toggle.
  btn.innerHTML = isFullscreen ? ICON_COMPRESS : ICON_EXPAND;
  btn.setAttribute('aria-label', isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen');
}
function toggleFullscreen() {
  if (!document.fullscreenElement) {
    const el = document.documentElement;
    const request = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
    if (request) request.call(el).catch(() => {});
  } else {
    const exit = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
    if (exit) exit.call(document).catch(() => {});
  }
}
// Keeps the icon correct even when fullscreen is exited a way other
// than tapping this button - the Esc key, or a tablet's own system
// gesture ("standard browser Fullscreen exit behavior may be used",
// per the request itself) - rather than only updating on click.
['fullscreenchange', 'webkitfullscreenchange', 'msfullscreenchange'].forEach(
  evt => document.addEventListener(evt, updateFullscreenIcon)
);
updateFullscreenIcon();

async function api(path, params) {
  const res = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: params}),
  });
  const data = await res.json();
  return data.result || {ok: false, error: 'Network error'};
}

async function loadOrders() {
  const mySeq = ++loadOrdersSeq;
  const res = await api('/flexsyskds/public/api/orders', {station_code: STATION_CODE, token: TOKEN});
  // Discard this response if a newer loadOrders() call has been issued
  // since this one started - see loadOrdersSeq's own comment above.
  if (mySeq !== loadOrdersSeq) {
    return;
  }
  const dot = document.getElementById('dot');
  const label = document.getElementById('connLabel');
  if (res.ok) {
    const isFirstLoad = KNOWN_ORDER_IDS === null;
    const newIds = new Set(res.orders.map(o => o.id));
    if (!isFirstLoad) {
      // Beep once per poll if any order id showed up that wasn't there
      // last time - not on the very first load (that would beep for
      // every order already sitting on screen when the page opens).
      const hasNewArrival = [...newIds].some(id => !KNOWN_ORDER_IDS.has(id));
      if (hasNewArrival) playBeep();
    }
    KNOWN_ORDER_IDS = newIds;

    // CANCELLATION VISIBILITY (dev request, point 5: "clearly
    // distinguishable cancellation notification/sound so kitchen staff
    // notice it quickly"): fires for a newly-cancelled *line*, whether
    // it's a single item cancelled on an otherwise-active order, or
    // every line on a fully-cancelled order (each line's own
    // cancelled_at still gets set individually by the cascade - see
    // kds_order.py::action_cancel() - so this same per-line check
    // naturally covers both cases without needing separate logic for
    // "was this a full-order cancel").
    const cancelledLineIds = new Set(
      res.orders.flatMap(o => o.lines.filter(l => l.state === 'cancelled').map(l => l.id))
    );
    const isFirstCancelCheck = KNOWN_CANCELLED_LINE_IDS === null;
    if (!isFirstCancelCheck) {
      const hasNewCancellation = [...cancelledLineIds].some(id => !KNOWN_CANCELLED_LINE_IDS.has(id));
      if (hasNewCancellation) playCancelAlert();
    }
    KNOWN_CANCELLED_LINE_IDS = cancelledLineIds;

    const nowReadyIds = new Set(
      // BUG-03 fix (see render()'s own detailed comment for the full
      // story): the celebration is specifically for "MY station's own
      // production just finished" - order.state alone requires every
      // station on a multi-station order to be done, which would
      // silently suppress the celebration for a station that finished
      // its own part while another station on the same shared order was
      // still working.
      res.orders.filter(o => {
        if (o.state === 'completed' || o.state === 'cancelled') return false;
        const lines = activeLines(o);
        return lines.length > 0 && lines.every(l => l.state === 'ready' || l.state === 'completed');
      }).map(o => o.id)
    );
    // Only the orders that JUST crossed into fully-Ready this poll get
    // the celebration spin - not every order that's already Ready (that
    // would replay it every 4s forever), and not on the very first load.
    CELEBRATE_IDS = isFirstLoad
      ? new Set()
      : new Set([...nowReadyIds].filter(id => !WAS_READY.has(id)));
    WAS_READY = nowReadyIds;

    ORDERS = res.orders;
    PRINTING_ENABLED = res.printing_enabled;
    dot.className = 'dot dot-on'; label.textContent = 'Online';
    document.getElementById('statOrders').textContent = res.stats.orders_count;
    document.getElementById('statAvg').textContent = res.stats.avg_prep_time || '--';
    document.getElementById('statLate').textContent = res.stats.late_count;
    render();
  } else {
    dot.className = 'dot dot-off'; label.textContent = 'Offline';
  }
}

function counts() {
  // REAL BUG FIX (BUG-10) - see render()'s own detailed comment. One
  // authoritative value per order, computed once, drives every count
  // below - eliminating the possibility of the same ticket incrementing
  // more than one bucket at once.
  const byStage = {};
  for (const o of ORDERS) {
    byStage[o.effective_stage] = (byStage[o.effective_stage] || 0) + 1;
  }
  return {
    all: ORDERS.length,
    new: byStage.new || 0,
    preparing: byStage.preparing || 0,
    ready: byStage.ready || 0,
    completed: byStage.completed || 0,
  };
}

function renderFilters() {
  const c = counts();
  const defs = [['all','ALL',c.all],['new','NEW',c.new],['preparing','PREPARING',c.preparing],['ready','READY',c.ready],['completed','COMPLETED',c.completed]];
  document.getElementById('filters').innerHTML = defs.map(([k,label,n]) => `
    <button class="fbtn ${FILTER===k?'active':''}" onclick="setFilter('${k}')">${label} <span class="fcount">${n}</span></button>
  `).join('');
}

function setFilter(f) { FILTER = f; render(); }

// Small inline SVGs (no external icon font - keeps the kiosk page fully
// self-contained). Kept intentionally simple per the reference design.
const ICON_STORE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l1-5h16l1 5"></path><path d="M4 9v10h16V9"></path><path d="M9 19v-6h6v6"></path></svg>';
const ICON_LAYERS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 8 12 14 22 8 12 2"></polygon><polyline points="2 14 12 20 22 14"></polyline></svg>';
const ICON_CLOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><polyline points="12 7 12 12 16 14"></polyline></svg>';
const ICON_PERSON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"></circle><path d="M4 20c0-4 4-6 8-6s8 2 8 6"></path></svg>';
const ICON_NOTE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="7" width="16" height="13" rx="2"></rect><path d="M9 7V5a3 3 0 0 1 6 0v2"></path></svg>';
const ICON_CHECK = '<svg class="icon-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';
const ICON_DASH = '<svg class="icon-dash" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line></svg>';
const ICON_CANCEL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';
const ICON_PRINT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>';

function elapsed(iso) {
  if (!iso) return '';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  const h = Math.floor(mins/60), m = mins%%60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function orderedAt(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
}

function cleanVariantInfo(text) {
  // The POS attribute-selection flow this reads from returns full
  // "question: answer" text per attribute (e.g. "Cup type (choose one):
  // paper cup"), joined with ", " for multiple attributes. Keeping only
  // the part after each segment's last ":" gives just the selected
  // values ("paper cup, medium, +30g") without the verbose questions -
  // a display-only cleanup; the raw value is untouched in the database.
  return text.split(', ').map(part => {
    const idx = part.lastIndexOf(':');
    return idx === -1 ? part.trim() : part.slice(idx + 1).trim();
  }).join(', ');
}

// BUG-09 FIX ("POS Quantity Delta Is Not Explicitly Communicated to
// Kitchen"): "1 x Pizza -> UPDATED" alone is operationally ambiguous -
// the kitchen can't tell whether 2 more are now needed or 2 fewer are.
// qty_delta (kds_order_line.py, backend field - not inferred from
// transient frontend state, per the dev request's own explicit
// requirement) makes this explicit: "UPDATED (+2)" or "UPDATED (-2)".
// Only rendered for line_change === 'updated' specifically - an ADDED
// line's own qty is already the full, unambiguous amount to prepare,
// and a delta suffix there would be redundant at best.
function qtyDeltaSuffix(l) {
  if (l.line_change !== 'updated' || !l.qty_delta) return '';
  const sign = l.qty_delta > 0 ? '+' : '';
  return ` (${sign}${l.qty_delta})`;
}

function lineNextAction(state) {
  // Mirrors the backend's LINE_TRANSITIONS: 'ready' is only a valid move
  // FROM 'preparing', not from 'new'/'accepted'. Computing each line's
  // own next action (rather than applying one action to every line on
  // the card) avoids silently-failing invalid-transition calls when a
  // single order has lines in different states at once (e.g. one item
  // already Preparing while another hasn't been Started yet).
  if (state === 'new' || state === 'accepted') return 'start';
  if (state === 'preparing') return 'ready';
  return null;
}

// CANCELLATION VISIBILITY (dev request): a cancelled line must never
// count toward "is this order still waiting on something" - matching
// the backend's own established pattern for the exact same question
// (kds_order.py's is_expeditor_ready already filters
// `l.state != 'cancelled'` before checking readiness). Before this
// existed, a single cancelled item on an otherwise-fully-ready order
// would make every "all lines done" check here return false forever
// (a cancelled line never satisfies state === 'ready'/'completed'),
// silently blocking the order from ever reaching its own COMPLETE
// button - a real, separate bug this feature surfaced while
// implementing it, not just a display change.
function activeLines(order) {
  return order.lines.filter(l => l.state !== 'cancelled');
}

// BUG-08 FIX ("Cancelled Lines Break Station Card Lifecycle / Terminal
// Cleanup"): a station whose lines are ALL terminal (completed and/or
// cancelled, with none of them genuinely active) needs to be classified
// two different ways depending on whether any of them actually
// finished:
//   - at least one line 'completed' -> this station's work genuinely
//     finished (Scenario A: "completed + cancelled" mix, or all-
//     completed) - treated as done/ready-style, matching how a plain
//     completed station already looked.
//   - zero lines 'completed' (every terminal line is 'cancelled') ->
//     nothing this station was working on ever finished (Scenario B) -
//     "preserve the last operational stage" instead: NEW if the
//     cancelled line(s) never even started, PREPARING if any reached
//     preparation_start_time before being cancelled, READY if any
//     reached ready_time. Point 3 of the dev request ("Terminal Line
//     Definition"): completed and cancelled both count as terminal for
//     "does this station have any active work left" purposes - the
//     distinction here is only about which STAGE label/visual to keep
//     showing, not about whether there's active work (there never is,
//     in either sub-case).
function stationLifecycle(order) {
  const lines = order.lines;
  const active = activeLines(order);
  if (active.length > 0) {
    return {hasActiveWork: true};
  }
  const hasAnyCompleted = lines.some(l => l.state === 'completed');
  if (hasAnyCompleted || !lines.length) {
    return {hasActiveWork: false, allCancelled: false};
  }
  // Every line is 'cancelled' specifically, zero completed - preserve
  // the last operational stage this station actually reached.
  const everReady = lines.some(l => l.ready_time);
  const everPreparing = lines.some(l => l.preparation_start_time);
  const lastStage = everReady ? 'ready' : everPreparing ? 'preparing' : 'new';
  return {hasActiveWork: false, allCancelled: true, lastStage: lastStage};
}

function mainAction(order) {
  // A fully-cancelled order (every line cancelled, order.state itself
  // 'cancelled') has nothing left to action at all.
  if (order.state === 'cancelled') return {action: null, label: 'CANCELLED'};
  // REAL BUG FIX, confirmed live on Odoo.sh (BUG-08, point 2: "No
  // Active Work = No Workflow Actions... authoritative from backend
  // payload/workflow eligibility, not only hidden with CSS"): a station
  // whose every line was cancelled (nothing ever completed either) must
  // never expose an action - checked first, before effective_stage is
  // even consulted, since a "preserved last stage" of e.g. 'preparing'
  // (BUG-08) must NOT be mistaken for a genuinely active preparing
  // station that still needs a READY tap.
  const lifecycle = stationLifecycle(order);
  if (!lifecycle.hasActiveWork && lifecycle.allCancelled) {
    return {action: null, label: 'CANCELLED'};
  }
  // BUG-10 FIX: driven by the same single authoritative
  // order.effective_stage every tab filter/count now uses (see
  // render()'s own detailed comment) - not a separately-maintained set
  // of activeLines()-based checks that happened to mostly agree with
  // it. BUG-07's own reasoning still applies throughout: every value
  // here is computed per-station, never from the order's own aggregate
  // `state` field, so Kitchen's own button is correct independent of
  // whatever Coffee/Bar are still doing on the same order.
  switch (order.effective_stage) {
    case 'new': return {action: 'start', label: 'START'};
    case 'preparing': return {action: 'ready', label: 'READY'};
    case 'ready': return {action: 'complete_station', label: 'COMPLETE'};
    case 'completed': return {action: null, label: 'COMPLETED'};
    default: return {action: null, label: 'CANCELLED'};
  }
}

function render() {
  renderFilters();
  let orders = ORDERS;
  // REAL BUG FIX, confirmed at runtime (dev request "Reopened READY
  // Order Appears in Multiple Stage Tabs", BUG-10): every tab filter
  // below used to run its own INDEPENDENT check ("does ANY line match
  // this tab's own state(s)?"), each entirely oblivious to the others -
  // a reopened order with one line back at 'new' (freshly added/reset
  // by a POS Delta) and another still 'preparing' satisfied BOTH
  // checks at once, so the same physical ticket counted under NEW *and*
  // PREPARING simultaneously ("NEW = 1, PREPARING = 1" for one ticket,
  // reported live), on top of everything BUG-03/BUG-07/BUG-08 already
  // had to separately account for (per-station Ready visibility,
  // completion, preserved-last-stage-while-cancelled). Replaced with
  // order.effective_stage - one authoritative value, computed once on
  // the backend (see controllers/kds.py's own _effective_stage() for
  // the full algorithm, identical here), used identically for the tab
  // filter/count below AND the card's own displayed status text -
  // structurally guaranteeing a ticket belongs to exactly one tab,
  // rather than relying on several independently-written checks to
  // happen to agree.
  if (FILTER !== 'all') {
    orders = orders.filter(o => o.effective_stage === FILTER);
  }

  const grid = document.getElementById('grid');
  if (!orders.length) { grid.innerHTML = '<div class="empty">No orders for this filter.</div>'; return; }

  grid.innerHTML = orders.map(order => {
    // Card frame color: blue = normal/active, red = late (even if it did
    // eventually get marked ready - still flags it finished late), green
    // = fully ready/completed, orange = warning/priority as before, grey
    // = fully cancelled (dev request "Cancellation Visibility
    // Improvement" - new).
    const act = mainAction(order);
    // REAL BUG FIX (BUG-10) - see render()'s own detailed comment: the
    // card's displayed status text and border color now read directly
    // from order.effective_stage, the exact same single authoritative
    // value driving the tab filters/counts above - previously two
    // separately-maintained local computations (anyNew/anyStarted/
    // allReady/allCompleted) that happened to mostly agree with the tab
    // logic via BUG-02's own "anyStarted before anyNew" precedence -
    // now there is structurally only one answer to "what stage is this
    // card in", not two parallel implementations that could drift.
    const lifecycle = stationLifecycle(order);
    const isCancelledTerminal = !lifecycle.hasActiveWork && lifecycle.allCancelled;
    // REAL BUG FIX ("CANCELLED FILTER CLASSIFICATION + RETENTION
    // LIFECYCLE", Issue 1): order.effective_stage itself is now the
    // distinct 'cancelled' value for this exact case (see
    // controllers/kds_kiosk.py's own _effective_stage() docstring for
    // the full explanation of why - "NEW = 6" with all 6 cards
    // genuinely CANCELLED, since effective_stage used to reuse the
    // "preserved last stage" value directly). The "was X" stage label
    // must therefore come from lifecycle.lastStage (stationLifecycle()
    // above, computed independently from ever_ready/ever_preparing
    // timestamps) instead of order.effective_stage, which no longer
    // carries that information - looking it up there now would
    // incorrectly read "CANCELLED (was undefined)".
    const stageLabel = {new: 'NEW', preparing: 'PREPARING', ready: 'READY', completed: 'COMPLETED'};
    const statusText = order.state === 'cancelled' ? 'CANCELLED'
      : isCancelledTerminal ? `CANCELLED (was ${stageLabel[lifecycle.lastStage]})`
      : stageLabel[order.effective_stage] || 'PREPARING';
    const isReadyOrDone = order.effective_stage === 'ready' || order.effective_stage === 'completed';
    const cardClass = order.state === 'cancelled' ? 'cancelled'
      : isCancelledTerminal ? 'cancelled'
      : order.sla_status === 'late' ? 'late'
      : isReadyOrDone ? 'ready'
      : order.sla_status === 'warning' ? 'warning'
      : order.priority !== 'normal' ? 'priority' : 'normal';
    const celebrateClass = CELEBRATE_IDS.has(order.id) ? 'celebrate' : '';

    const linesHtml = order.lines.map(l => {
      // CANCELLATION VISIBILITY (dev request, point 1: "the cancelled
      // line should remain temporarily visible and clearly display
      // CANCELLED... visually distinguishable from active preparation
      // lines"): a cancelled line keeps its normal place in the list
      // (never removed - see the grace-period query fix in this
      // controller's own get_orders() for why it's still in `order` at
      // all) but renders distinctly: no interactive checkbox (nothing
      // left to action on it), struck-through text, and an explicit
      // CANCELLED badge instead of any variant/change badge.
      if (l.state === 'cancelled') {
        return `
      <div class="line-item line-cancelled">
        <div class="line-checkbox line-checkbox-cancelled">${ICON_CANCEL}</div>
        <div class="line-main">
          <div class="line-title-row">
            <span class="line-title">${l.qty} × ${l.product_name}</span>
            <span class="line-badge line-badge-cancelled">CANCELLED</span>
          </div>
        </div>
      </div>`;
      }
      const checkboxState = (l.state === 'ready' || l.state === 'completed') ? 'checked' : l.state === 'preparing' ? 'in-progress' : '';
      const nextAction = lineNextAction(l.state);
      return `
      <div class="line-item">
        <div class="line-checkbox ${checkboxState}"
             ${nextAction ? `onclick="advanceLine(${order.id}, ${l.id}, '${nextAction}')"` : ''}>
          ${ICON_CHECK}${ICON_DASH}
        </div>
        <div class="line-main">
          <div class="line-title-row">
            <span class="line-title">${l.qty} × ${l.product_name}</span>
            ${l.variant_info ? `<span class="variant-pill">${cleanVariantInfo(l.variant_info)}</span>` : ''}
            ${l.line_change && l.line_change !== 'none' ? `<span class="line-badge">${l.line_change_label}${qtyDeltaSuffix(l)}</span>` : ''}
          </div>
          ${l.note ? `<div class="line-note-row">${ICON_NOTE}<span>${l.note}</span></div>` : ''}
        </div>
      </div>`;
    }).join('');

    // Headline shows the actual POS receipt number (what the customer
    // and cashier both already recognize) rather than the internal
    // kds.order sequence - falls back to the internal name only for
    // orders with no linked POS order (future QR/web/API sources).
    const headline = order.pos_reference || order.name;
    const hasCustomerName = order.customer_name && order.customer_name !== order.pos_reference;

    return `
      <div class="card ${cardClass} ${celebrateClass}">
        <div class="card-head">
          ${order.priority !== 'normal' ? `<div class="ribbon">${order.priority_label}</div>` : ''}
          <div class="card-title-row">
            <div class="accent-bar"></div>
            <div>
              <div class="order-no">${headline}</div>
              <div class="ordered-ref">#${order.name} &middot; ${orderedAt(order.created_time)}</div>
            </div>
          </div>
          <div class="chips-row">
            <span class="chip">${ICON_STORE}${order.order_type_label}</span>
            ${order.table_label ? `<span class="chip">${ICON_LAYERS}${order.table_label}</span>` : ''}
            <span class="chip chip-timer ${order.sla_status === 'late' ? 'pulse' : ''}">${ICON_CLOCK}${elapsed(order.created_time)}</span>
          </div>
          <div class="status-blink"><span class="dot"></span>${statusText}</div>
          ${hasCustomerName ? `<div class="customer-name">${order.customer_name}</div>` : ''}
          ${order.employee_name ? `<div class="employee-row">${order.employee_name}${ICON_PERSON}</div>` : ''}
        </div>
        <div class="card-body">${linesHtml}</div>
        <div class="card-footer">
          <button class="print-act" ${PRINTING_ENABLED ? '' : 'disabled'} onclick="printOrder(${order.id})" title="${PRINTING_ENABLED ? '' : 'Printing is not enabled for this station'}">${ICON_PRINT}</button>
          ${act.action === null
            ? '' /* Real COMPLETED tab (dev request): "There should no longer be a DONE button because the order is already completed" - no button at all now, not even a disabled one. The COMPLETED status text/badge on the card is the sole indicator. */
            : `<button class="main-act" onclick="advance(${order.id})">${act.label}${ICON_CHECK}</button>`}
        </div>
      </div>
    `;
  }).join('');
}

async function advance(orderId) {
  const order = ORDERS.find(o => o.id === orderId);
  if (!order) return;
  const act = mainAction(order);
  if (act.action === 'complete_station') {
    // BUG-07 FIX ("Station COMPLETE does not transition from READY"):
    // was an order-level call (order_complete) - completing this
    // station's own ready lines individually instead, the same way
    // 'start'/'ready' already advance each line on this card one at a
    // time below. Only lines actually sitting at 'ready' get the call
    // (a line already 'completed' - possible mid-batch if this ever
    // races with something else touching the same card - is simply
    // skipped, not re-completed).
    for (const line of activeLines(order)) {
      if (line.state === 'ready') {
        await api('/flexsyskds/public/api/action', {station_code: STATION_CODE, token: TOKEN, line_id: line.id, action: 'complete'});
      }
    }
    loadOrders();
    return;
  }
  for (const line of order.lines) {
    const lineAct = lineNextAction(line.state);
    if (lineAct) {
      await api('/flexsyskds/public/api/action', {station_code: STATION_CODE, token: TOKEN, line_id: line.id, action: lineAct});
    }
  }
  loadOrders();
}

async function advanceLine(orderId, lineId, action) {
  // Checkbox click on a single line - advances just that one item, unlike
  // the card's main button which advances every remaining line at once.
  await api('/flexsyskds/public/api/action', {station_code: STATION_CODE, token: TOKEN, line_id: lineId, action: action});
  loadOrders();
}

async function printOrder(orderId) {
  if (!PRINTING_ENABLED) return;
  await api('/flexsyskds/public/api/print', {station_code: STATION_CODE, token: TOKEN, order_id: orderId});
}

loadOrders();
setInterval(loadOrders, 4000);
</script>
</body>
</html>
"""
