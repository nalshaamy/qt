# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class KdsPrinter(models.Model):
    _name = 'kds.printer'
    _description = 'FlexSys KDS Printer'
    _order = 'name'

    name = fields.Char(required=True)

    agent_key = fields.Char(
        string='Print Agent Key', copy=False, groups='flexsys_kds.group_kds_administrator',
        help="Shared secret used by the local print agent/bridge process to "
             "poll and report on this printer's jobs via the "
             "/flexsys_kds/print/agent/* routes, instead of a full Odoo "
             "user session. Rotate it if you suspect it has leaked."
    )
    station_id = fields.Many2one('kds.station', string='Station', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='station_id.company_id', store=True)

    printer_type = fields.Selection([
        ('network', 'Network Printer'),
        ('usb', 'USB Printer'),
        ('thermal', 'Thermal Printer'),
    ], default='network', required=True)

    ip_address = fields.Char(string='IP / Network Address')
    port = fields.Char(default='9100')
    usb_identifier = fields.Char(string='USB / Device ID')
    model = fields.Char()
    serial_number = fields.Char()

    is_default = fields.Boolean(string='Default Printer')
    is_backup = fields.Boolean(string='Backup / Fallback Printer')

    status = fields.Selection([
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('error', 'Error'),
    ], default='online')
    last_seen = fields.Datetime()
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('agent_key', secrets.token_urlsafe(24))
        return super().create(vals_list)

    def action_regenerate_agent_key(self):
        for printer in self:
            printer.agent_key = secrets.token_urlsafe(24)

    def action_show_agent_key(self):
        """UI/DATA FIX ("Printing Configuration Gap - Agent Key
        Access" / "Rename/Fix Agent Key Action"), confirmed live:
        `agent_key` is displayed with `password="True"` on the form
        (masked, as it should be for a genuine secret) - but this left
        no way at all to actually retrieve the real value to configure
        the external print agent process with.

        REAL FIX (naming correction, confirmed live): this method was
        originally named/labeled `action_copy_agent_key()` / "Copy
        Agent Key," implying an automatic clipboard copy - it never
        actually did that; it only ever revealed the key in a sticky
        notification for manual selection. Renamed to
        `action_show_agent_key()` / "Show Agent Key" to accurately
        describe the real, unchanged behavior, rather than adding
        genuine `navigator.clipboard` JavaScript to make the old name
        true - the client's own explicit choice, given that any such
        addition would be new, currently-unverified frontend code, and
        "Show Agent Key is acceptable as long as the full key can be
        selected and copied manually," which this already satisfies
        exactly, unchanged.

        Deliberately the lowest-risk possible design: a plain Python
        server action, returning Odoo's own standard, officially
        documented `ir.actions.client` / `display_notification`
        mechanism - no custom JavaScript at all, no new widget. The key
        is shown once, in a `sticky: True` notification (stays on
        screen until the person dismisses it, not a few-second toast) -
        long enough to select and copy the text manually (Ctrl+C) -
        never written back into the form itself, never rendered
        unmasked in the persistent `agent_key` field, and never logged
        anywhere. "Do not display the key permanently in plain text" is
        honored exactly, since the field itself is completely
        unaffected and stays password-masked at all other times.

        `action_regenerate_agent_key()` (above) is completely
        untouched - this method never writes to `agent_key` at all, so
        revealing the key can never accidentally change it.

        Access is enforced the same way `action_regenerate_agent_key()`
        already is: `groups="flexsys_kds.group_kds_administrator"` on
        the button itself (view-level, hides the button entirely for
        anyone else - see kds_printer_views.xml), backed here by an
        explicit, defense-in-depth server-side check as well, since a
        view-level `groups` attribute alone is a UI convenience, not a
        real access boundary on its own - matching `agent_key` field's
        own already-existing `groups=` restriction at the ORM level.

        REAL BUG FIX ("Print Agent Authentication - Live Test
        Failure"), confirmed live: a print agent claim attempt using a
        key "obtained from the Printer form after regeneration" failed
        authentication despite the stored and compared values (traced
        end to end - see controllers/kds.py's own
        `_printer_from_key()`) being genuinely correct and unchanged at
        every step. The received key was 49 characters long - `secrets.
        token_urlsafe(24)` always generates exactly 32 (confirmed
        directly, 50 trials, zero variance) - a 17-character excess
        matching `len("Print Agent Key: ")` exactly. The strong
        conclusion: this notification's own title and message sit close
        together visually in Odoo's own standard rendering, with no
        strong visual break preventing a manual text selection from
        accidentally spanning both - the administrator most likely
        selected and copied the title text along with the actual key.
        The underlying VALUE was never wrong; the DISPLAY made a manual
        copy error easy to make without noticing.

        Fixed by restructuring the message itself (not the title, which
        Odoo's own notification component still renders as a distinct,
        bolded UI element) into two clearly-separated parts: the key
        ALONE, as the very first line (so a copy starting from the very
        beginning of the message body never needs to skip past
        anything else first), followed by a blank line and then a
        plain-language verification hint (its own current length, in
        English prose - visually and structurally unmistakable from a
        base64 key even if accidentally included in a copy) - "copy the
        line above only." This does not, and cannot, guarantee no
        future copy error is ever possible (this is still manual
        selection from a browser notification, not a genuine automatic
        clipboard copy - the client's own explicitly accepted trade-off
        when choosing "Show" over new, unverified `navigator.clipboard`
        JavaScript), but it directly targets the confirmed, specific
        failure mode found here.
        """
        self.ensure_one()
        if not self.env.user.has_group('flexsys_kds.group_kds_administrator'):
            raise AccessError(_("Only a KDS Administrator can view the Print Agent Key."))
        if self.agent_key:
            message = "%s\n\n%s" % (
                self.agent_key,
                _("(%(length)d characters - select and copy the line above only)")
                % {'length': len(self.agent_key)},
            )
        else:
            message = _("This printer has no Print Agent Key set.")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Print Agent Key"),
                'message': message,
                'type': 'info',
                'sticky': True,
            },
        }

    def action_test_connection(self):
        """AUDIT FIX ("Printer Connection Test - Known Limitation",
        DOCUMENTATION/FUTURE): this does NOT verify real physical printer
        connectivity - it never has. Odoo's role in printing is managing
        Print Jobs, the atomic Claim/Lease mechanism, and the versioned
        print payload contract (see
        kds.print.job._claim_pending_jobs()/._print_payload()) - actually
        talking to a physical printer (ESC/POS, network socket, IoT box,
        etc.) is the external Print Agent's job, a separate process not
        included in this module (see docs/PRINT_AGENT.md's own
        "Architecture at a glance" section).

        UI/DATA FIX ("Master Change Request", item 14, "Printer Form
        Cleanup"): "REMOVE من Production UI: Mark as Online (No Real
        Connectivity Check)." The button that called this method is
        removed from the printer form's own view (kds_printer_views.xml)
        - see docs/PRINT_AGENT.md's own new "What 'Status: Online'
        actually means" section for the full reasoning: this button let
        anyone flip `status` to 'online' with zero connectivity
        verification, mixed in with the same field genuinely being set
        by a real agent's own successful job report
        (controllers/kds.py's own agent_result()) - an unreliable,
        misleading mix exactly matching item 13's own concern that
        "Online" must never imply the physical printer itself is
        verified reachable.

        The method itself is deliberately kept in the codebase rather
        than deleted outright - purely for a future testing/demo
        scenario that might still genuinely need a manual override like
        this, reachable via Developer Mode or a direct RPC call if ever
        needed again - but it is no longer part of the normal,
        day-to-day production UI.
        """
        self.ensure_one()
        self.write({'last_seen': fields.Datetime.now(), 'status': 'online'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('FlexSys KDS'),
                'message': _(
                    "'%s' marked Online. This does NOT verify a real physical "
                    "connection - only the external Print Agent, once connected, "
                    "can confirm that."
                ) % self.name,
                'type': 'warning',
                'sticky': True,
            },
        }

    def action_set_default(self):
        self.ensure_one()
        self.station_id.printer_ids.write({'is_default': False})
        self.is_default = True

    def action_set_backup(self):
        self.ensure_one()
        self.station_id.printer_ids.write({'is_backup': False})
        self.is_backup = True
