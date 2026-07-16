from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    show_in_qr_menu = fields.Boolean(string='Show in QR Menu')
    available_in_qr_menu = fields.Boolean(string='Available in QR Menu', default=True)
    qr_menu_category_id = fields.Many2one('qtcafe.qr.menu.category', string='QR Menu Category')
    qr_display_order = fields.Integer(string='QR Display Order', default=10)
    qr_menu_description = fields.Text(string='QR Short Description')
    qr_image = fields.Image(string='QR Menu Image', max_width=1024, max_height=1024)
