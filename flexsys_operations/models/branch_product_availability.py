# -*- coding: utf-8 -*-
from odoo import fields, models


class FlexSysOperationsBranchProductAvailability(models.Model):
    _name = 'flexsys.operations.product.availability'
    _description = 'QR Product Availability by POS Branch'
    _rec_name = 'product_tmpl_id'

    pos_config_id = fields.Many2one('pos.config', required=True, ondelete='cascade', index=True)
    product_tmpl_id = fields.Many2one('product.template', required=True, ondelete='cascade', index=True)
    available = fields.Boolean(default=True, required=True)

    _operations_branch_product_unique = models.Constraint(
        'unique(pos_config_id, product_tmpl_id)',
        'Product availability can only be defined once per POS branch.',
    )
