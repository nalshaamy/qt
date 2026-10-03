from odoo import Command, fields, models


class FlexSysMenuSetupWizard(models.TransientModel):
    _name = "flexsys.menu.setup.wizard"
    _description = "FlexSys Digital Menu Setup Wizard"

    name = fields.Char(required=True, default="Main Menu")
    slug = fields.Char(required=True, default="main")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    public_domain = fields.Char()
    logo = fields.Image(max_width=1600, max_height=1600)
    product_tmpl_ids = fields.Many2many(
        "product.template",
        string="Products",
        domain="[('available_in_pos', '=', True), ('sale_ok', '=', True)]",
    )
    pos_config_ids = fields.Many2many("pos.config", string="Branches / POS", domain="[('company_id', '=', company_id)]")
    pricelist_id = fields.Many2one("product.pricelist", check_company=True)
    default_language = fields.Selection([("ar", "Arabic"), ("en", "English")], default="ar", required=True)

    def action_create_menu(self):
        self.ensure_one()
        menu = self.env["flexsys.menu"].create({
            "name": self.name,
            "slug": self.slug,
            "company_id": self.company_id.id,
            "public_domain": self.public_domain,
            "logo": self.logo,
            "pos_config_ids": [Command.set(self.pos_config_ids.ids)],
            "pricelist_id": self.pricelist_id.id,
            "default_language": self.default_language,
        })
        category = self.env["flexsys.menu.category"].create({
            "name": "Menu",
            "menu_id": menu.id,
            "sequence": 10,
        })
        for sequence, product in enumerate(self.product_tmpl_ids, start=10):
            self.env["flexsys.menu.product"].create({
                "menu_id": menu.id,
                "product_tmpl_id": product.id,
                "category_id": category.id,
                "sequence": sequence,
                "visibility": "visible",
            })
        if self.logo:
            menu.action_generate_brand()
        menu.action_generate_qr()
        return {
            "type": "ir.actions.act_window",
            "name": "Digital Menu",
            "res_model": "flexsys.menu",
            "res_id": menu.id,
            "view_mode": "form",
            "target": "current",
        }
