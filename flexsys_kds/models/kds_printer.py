# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models


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

    def action_test_connection(self):
        """AUDIT FIX ("Printer Connection Test - Known Limitation",
        DOCUMENTATION/FUTURE): this does NOT verify real physical printer
        connectivity - it never has - and the button/message below are
        now explicit about that rather than implying otherwise. Odoo's
        role in printing is managing Print Jobs, the atomic Claim/Lease
        mechanism, and the versioned print payload contract (see
        kds.print.job._claim_pending_jobs()/._print_payload()) - actually
        talking to a physical printer (ESC/POS, network socket, IoT box,
        etc.) is the external Print Agent's job, a separate process not
        included in this module (see README's Printing section). This
        button exists only as a quick way to mark a printer record
        'online' for testing/demo purposes without needing a live agent
        connected yet."""
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
