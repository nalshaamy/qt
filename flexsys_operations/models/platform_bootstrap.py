# -*- coding: utf-8 -*-
from odoo import api, models


class FlexSysPlatformUser(models.Model):
    _inherit = 'flexsys.platform.user'

    @api.model
    def bootstrap_operations_access(self):
        """Finish Operations registration safely on install and upgrade.

        The platform administrator role already receives the Operations
        permissions through XML. Existing bootstrap users created before roles
        were introduced may still have no role at all; assigning the platform
        administrator role only to those unconfigured users makes the first
        workspace immediately usable without overriding deliberate role choices.
        """
        admin_role = self.env.ref(
            'flexsys_platform.role_platform_admin',
            raise_if_not_found=False,
        )
        if admin_role:
            users_without_roles = self.sudo().search([
                ('active', '=', True),
                ('role_ids', '=', False),
            ])
            if users_without_roles:
                users_without_roles.write({'role_ids': [(4, admin_role.id)]})

        application = self.env['flexsys.platform.application'].sudo().search([
            ('code', '=', 'operations'),
        ], limit=1)
        if application:
            values = {
                'version': '19.0.3.0.4',
                'health_status': 'healthy',
                'health_message': 'Operations workspace is registered and available.',
            }
            # readonly=True is a UI restriction; server-side registration owns
            # these health fields and may update them deliberately.
            application.write(values)
        return True
