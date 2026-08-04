# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FlexSysOperationsRoutingSettings(models.TransientModel):
    _name = 'flexsys.operations.routing.settings'
    _description = 'Operations Order Routing Settings'
    _rec_name = 'name'

    name = fields.Char(
        string='Name',
        default='Operations Order Routing',
        readonly=True,
    )

    fallback_pos_config_id = fields.Many2one(
        'pos.config',
        string='Fallback POS',
        domain=[('operations_branch_enabled', '=', True)],
        help='Used only when no branch/POS was selected or supplied.',
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        raw_id = self.env['ir.config_parameter'].sudo().get_param(
            'operations_qr_order.default_pos_config_id'
        )
        if raw_id:
            try:
                values['fallback_pos_config_id'] = int(raw_id)
            except (TypeError, ValueError):
                pass
        return values

    def action_save(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(
            'operations_qr_order.default_pos_config_id',
            self.fallback_pos_config_id.id or '',
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'FlexSys',
                'message': 'Routing settings saved successfully.',
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window_close',
                },
            },
        }
