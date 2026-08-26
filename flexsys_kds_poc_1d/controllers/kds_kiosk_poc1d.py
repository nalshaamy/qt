# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

from odoo.addons.flexsys_kds.controllers.kds_kiosk import (
    FlexSysKdsKioskController,
    _station_from_token,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# FlexSys KDS - POC-1D ONLY (TEMPORARY, NOT COMMERCIAL CODE)
#
# Runtime extension of flexsys_kds's own Public Kiosk page - the same
# spirit as the JS patch() mechanism used for Internal KDS, never a
# rewrite of flexsys_kds's own controller file. kiosk_page() below
# calls the ORIGINAL, unmodified handler first via super(), then only
# appends one small injection snippet right before </body> - the
# original response is otherwise untouched.
#
# _station_from_token is flexsys_kds's own single, central token-
# validation function (already used by every one of its four public
# kiosk routes) - reused here directly, never re-implemented or
# weakened, for the one new route this module adds.
# ---------------------------------------------------------------------

_POC_INJECT_SNIPPET = """
<script src="/flexsys_kds_poc_1d/static/src/shared/flexsys_ticket_renderer.js"></script>
<script src="/flexsys_kds_poc_1d/static/src/public/flexsys_epos_direct_public.js"></script>
<script>
(function () {
  // FlexSys KDS - POC-1D Public Kiosk print integration (TEMPORARY).
  // Fetches this station's own printing config from the new POC-only
  // route below (station_id, station_name, flexsys_printing_method,
  // flexsys_printer_ip, flexsys_use_local_network_access ONLY - no
  // Agent Key, no printer secrets), then wraps the EXISTING global
  // printOrder(orderId) function (defined earlier in this same page
  // by flexsys_kds's own unmodified template) so a 'direct_network'
  // station uses the Direct ePOS Adapter above instead of the legacy
  // /flexsyskds/public/api/print route - any other station falls
  // through to the original, completely unchanged.
  var flexsysPoc1dConfig = null;

  async function flexsysPoc1dLoadConfig() {
    try {
      var res = await api('/flexsys_kds_poc_1d/public/printing_config/' + STATION_CODE + '/' + TOKEN, {});
      if (res && res.ok) {
        flexsysPoc1dConfig = res;
        console.log('FlexSys POC-1D (Kiosk): printing config loaded ->', res);
      } else {
        console.error('FlexSys POC-1D (Kiosk): failed to load printing config ->', res);
      }
    } catch (e) {
      console.error('FlexSys POC-1D (Kiosk): error loading printing config.', e);
    }
  }

  var flexsysPoc1dOriginalPrintOrder = window.printOrder;

  window.printOrder = async function (orderId) {
    console.log('=== FlexSys POC-1D (Kiosk): Card Print clicked ===');
    console.log('FlexSys POC-1D (Kiosk): orderId ->', orderId);

    if (!flexsysPoc1dConfig) {
      await flexsysPoc1dLoadConfig();
    }

    if (!flexsysPoc1dConfig || flexsysPoc1dConfig.flexsys_printing_method !== 'direct_network') {
      console.log(
        'FlexSys POC-1D (Kiosk): this station is not Direct Network - ' +
        'falling back to the existing legacy print flow, exactly as ' +
        'before this integration was added.'
      );
      return flexsysPoc1dOriginalPrintOrder(orderId);
    }

    if (!flexsysPoc1dConfig.flexsys_printer_ip) {
      console.error(
        'FlexSys POC-1D (Kiosk) FAIL: Printing Method is Direct ' +
        'Network but Printer IP is empty on this station.'
      );
      return;
    }

    // REAL TICKET RENDERING ROUND: find the full order object this
    // page already holds locally (the ORDERS global array, populated
    // by loadOrders() from flexsys_kds's own unmodified
    // kiosk_orders() response - the exact same product_name/qty/
    // variant_info/note/line_change shape confirmed by reading
    // controllers/kds_kiosk.py before writing this) - no extra
    // network round-trip needed. Normalized via the ONE shared
    // function also used by the Internal KDS integration, so both
    // screens make an identical "which raw fields feed the ticket"
    // decision.
    var rawOrder = null;
    for (var i = 0; i < ORDERS.length; i++) {
      if (ORDERS[i].id === orderId) {
        rawOrder = ORDERS[i];
        break;
      }
    }
    if (!rawOrder) {
      console.error(
        'FlexSys POC-1D (Kiosk) FAIL: order id ' + orderId +
        ' not found in ORDERS - cannot build a real ticket.'
      );
      return;
    }
    // FIX ("Real Raster Ticket Consolidated Review", item 1): 'NEW'
    // for this round's own test print - the real REPRINT/ADDED/
    // UPDATED/CANCELLED decision is deferred to the "Direct Printing
    // <-> kds.print.job" Baseline phase, driven by actual print
    // history, never browser local state.
    var normalizedOrder = window.FlexSysTicketBuilder.normalizeOrderForTicket(
      rawOrder, flexsysPoc1dConfig.station_name, 'NEW', flexsysPoc1dConfig.branch_name
    );
    console.log('FlexSys POC-1D (Kiosk): normalized order ->', normalizedOrder);

    var result = await window.FlexSysKDSPrint.printDirectEpos({
      ip: flexsysPoc1dConfig.flexsys_printer_ip,
      useLocalNetworkAccess: flexsysPoc1dConfig.flexsys_use_local_network_access,
      normalizedOrder: normalizedOrder,
    });

    console.log('=== FlexSys POC-1D (Kiosk): Card Print finished ===');
    console.log('FlexSys POC-1D (Kiosk): adapter result ->', result);
  };

  flexsysPoc1dLoadConfig();
})();
</script>
</body>"""


class FlexSysKdsKioskControllerPoc1d(FlexSysKdsKioskController):

    @http.route('/flexsyskds/public/<string:station_code>/<string:token>',
                type='http', auth='public', website=False)
    def kiosk_page(self, station_code, token, **kwargs):
        response = super().kiosk_page(station_code, token, **kwargs)
        try:
            html = response.data.decode('utf-8')
            if '</body>' in html:
                html = html.replace('</body>', _POC_INJECT_SNIPPET, 1)
                response.data = html.encode('utf-8')
            else:
                _logger.warning(
                    "FlexSys POC-1D: expected '</body>' not found in "
                    "the Kiosk page's own HTML - print integration "
                    "script was NOT injected. The page itself is "
                    "still served normally via the original handler."
                )
        except Exception:
            _logger.exception(
                "FlexSys POC-1D: failed to inject the Public Kiosk "
                "print-integration script - the kiosk page itself is "
                "still served normally, unmodified, via the original "
                "handler's own response."
            )
        return response

    @http.route('/flexsys_kds_poc_1d/public/printing_config/<string:station_code>/<string:token>',
                type='jsonrpc', auth='public', csrf=False)
    def poc1d_printing_config(self, station_code, token):
        station = _station_from_token(request.env, station_code, token)
        if not station:
            return {'ok': False, 'error': 'invalid_token'}
        # Deliberately minimal - only what this POC's own frontend
        # needs. No Agent Key, no printer secrets. branch_name added
        # this round (station.company_id.name) - not a credential or
        # secret, needed purely so Internal KDS and Public Kiosk print
        # the same ticket content; without it, Internal KDS's own
        # order.company_name would print a branch name Public Kiosk's
        # own ticket silently omitted, which is exactly the
        # Internal/Public parity gap flagged this round.
        return {
            'ok': True,
            'station_id': station.id,
            'station_name': station.name,
            'branch_name': station.company_id.name or '',
            'flexsys_printing_method': station.flexsys_printing_method,
            'flexsys_printer_ip': station.flexsys_printer_ip or '',
            'flexsys_use_local_network_access': bool(station.flexsys_use_local_network_access),
        }
