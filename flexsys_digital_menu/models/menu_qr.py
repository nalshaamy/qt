from odoo import fields, models


class FlexSysMenuQR(models.Model):
    _name = "flexsys.menu.qr"
    _description = "FlexSys Digital Menu QR Code"
    _order = "write_date desc, id desc"

    menu_id = fields.Many2one("flexsys.menu", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="menu_id.company_id", store=True, index=True)
    url = fields.Char(required=True)
    png = fields.Binary(attachment=True)
    svg = fields.Binary(attachment=True)
    png_filename = fields.Char(compute="_compute_filenames")
    svg_filename = fields.Char(compute="_compute_filenames")

    def _compute_filenames(self):
        for record in self:
            slug = record.menu_id.slug or "menu"
            record.png_filename = f"{slug}-qr.png"
            record.svg_filename = f"{slug}-qr.svg"

    _sql_constraints = [
        ("one_qr_per_menu", "unique(menu_id)", "Only one active QR record is kept per menu."),
    ]
