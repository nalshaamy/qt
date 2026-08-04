import socket
from odoo import fields, models, _
from odoo.exceptions import UserError


class FlexSysOperationsQrPrinterConfig(models.Model):
    _name = 'flexsys.operations.printer.config'
    _description = 'FlexSys QR Printer Settings'

    name = fields.Char(default='Cashier Printer', required=True)
    active = fields.Boolean(default=True)
    auto_print_on_accept = fields.Boolean(string='Auto Print on Accept', default=False)
    printer_ip = fields.Char(string='Printer IP')
    printer_port = fields.Integer(string='Printer Port', default=9100)
    shop_name = fields.Char(string='Receipt Shop Name', default='FlexSys')
    copies = fields.Integer(default=1)
    timeout = fields.Integer(default=5, help='Network timeout in seconds')

    def _get_active_config(self):
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            config = self.create({'name': 'Cashier Printer'})
        return config

    def _validate_printer(self):
        self.ensure_one()
        if not self.printer_ip:
            raise UserError(_('Please set the printer IP address.'))
        if not self.printer_port:
            raise UserError(_('Please set the printer port.'))

    def _encode_receipt(self, text):
        # Epson ESC/POS basic commands. Arabic support depends on printer firmware/codepage.
        # CP864 is commonly used for Arabic on ESC/POS printers.
        data = b'\x1b@'  # initialize
        data += b'\x1bt\x16'  # select CP864 when supported
        try:
            data += text.encode('cp864', errors='replace')
        except Exception:
            data += text.encode('utf-8', errors='replace')
        data += b'\n\n\n\x1dV\x00'  # feed and cut
        return data

    def print_text(self, text):
        self.ensure_one()
        self._validate_printer()
        payload = self._encode_receipt(text)
        copies = max(self.copies or 1, 1)
        try:
            for _i in range(copies):
                with socket.create_connection((self.printer_ip, int(self.printer_port)), timeout=self.timeout or 5) as sock:
                    sock.sendall(payload)
        except OSError as exc:
            raise UserError(_('Could not connect to Epson printer %s:%s. %s') % (self.printer_ip, self.printer_port, exc))
        return True

    def action_test_printer(self):
        for config in self:
            config.print_text('%s\n%s\n\nTest Print OK\n' % (config.shop_name or 'FlexSys', fields.Datetime.now()))
        return True
