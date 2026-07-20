from odoo import api, fields, models


class QtCafeQrOrderLine(models.Model):
    _name = 'qtcafe.qr.order.line'
    _description = 'QT Cafe QR Order Line'

    order_id = fields.Many2one('qtcafe.qr.order', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True)
    name = fields.Char(string='Product Description', related='product_id.display_name', store=True)
    qty = fields.Float(default=1)
    price_unit = fields.Monetary()
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id')
    note = fields.Char(string='Options / Add-ons')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.lst_price

    @api.depends('qty', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.qty * line.price_unit
