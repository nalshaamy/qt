# -*- coding: utf-8 -*-
# FLPOS - Point of Sale configuration fields.

from odoo import api, fields, models


class PosConfig(models.Model):
    """Store FLPOS options separately for every Point of Sale configuration."""

    _inherit = "pos.config"

    # Receipt configuration
    flexsys_enable_custom_receipt_logo = fields.Boolean(
        string="Enable Custom Receipt Logo",
        default=True,
        help="Enable the dedicated FLPOS logo on customer receipts.",
    )
    flexsys_receipt_logo = fields.Image(
        string="Customer Receipt Logo",
        attachment=True,
        max_width=600,
        max_height=300,
        help=(
            "A dedicated receipt logo independent from the company logo. "
            "Odoo resizes it automatically to protect POS performance."
        ),
    )
    flexsys_has_receipt_logo = fields.Boolean(
        string="Has Customer Receipt Logo",
        compute="_compute_flexsys_has_receipt_logo",
        store=True,
        help="Technical flag used by the POS receipt without loading the image binary.",
    )
    flexsys_hide_company_logo = fields.Boolean(
        string="Hide Company Logo",
        default=True,
        help="Hide the standard company logo from customer receipts.",
    )
    flexsys_hide_powered_by_odoo = fields.Boolean(
        string="Hide Powered by Odoo",
        default=True,
        help="Remove the Powered by Odoo line from customer receipts.",
    )

    flexsys_receipt_template_ids = fields.One2many(
        "flexsys.pos.receipt.template",
        "pos_config_id",
        string="Receipt Templates",
    )
    flexsys_receipt_design = fields.Json(
        string="Active Receipt Studio Design",
        compute="_compute_flexsys_receipt_design",
        help="Compact active Receipt Studio design loaded by the POS client.",
    )

    # Closing report configuration
    flexsys_enable_thermal_closing_report = fields.Boolean(
        string="Enable Thermal Closing Report",
        default=False,
        help="Enable the FLPOS closing report designed for thermal printers.",
    )
    flexsys_enable_a4_closing_report = fields.Boolean(
        string="Enable A4 Closing Report",
        default=True,
        help="Enable the FLPOS A4 session closing report.",
    )

    @api.model
    def _load_pos_data_read(self, records, config):
        """Keep the receipt logo binary out of the POS offline payload.

        The POS only needs the boolean flags. The image itself is served lazily
        through /web/image when the receipt is rendered.
        """
        loaded_records = super()._load_pos_data_read(records, config)
        records_by_id = {record.id: record for record in records}
        for loaded_record in loaded_records:
            loaded_record.pop("flexsys_receipt_logo", None)
            record = records_by_id.get(loaded_record.get("id"))
            if record:
                loaded_record["flexsys_receipt_design"] = record.flexsys_receipt_design or False
        return loaded_records

    @api.depends(
        "flexsys_receipt_template_ids.active",
        "flexsys_receipt_template_ids.is_default",
        "flexsys_receipt_template_ids.block_ids.sequence",
        "flexsys_receipt_template_ids.block_ids.enabled",
        "flexsys_receipt_template_ids.block_ids.block_type",
        "flexsys_receipt_template_ids.block_ids.title",
        "flexsys_receipt_template_ids.block_ids.show_title",
        "flexsys_receipt_template_ids.block_ids.content",
        "flexsys_receipt_template_ids.block_ids.alignment",
        "flexsys_receipt_template_ids.block_ids.font_size",
        "flexsys_receipt_template_ids.block_ids.bold",
    )
    def _compute_flexsys_receipt_design(self):
        """Expose the active Receipt Studio template as a compact POS payload."""
        for config in self:
            template = config.flexsys_receipt_template_ids.filtered(
                lambda item: item.active and item.is_default
            )[:1]
            if not template:
                config.flexsys_receipt_design = False
                continue

            blocks = []
            for block in template.block_ids.filtered("enabled").sorted("sequence"):
                blocks.append({
                    "id": block.id,
                    "type": block.block_type,
                    "title": block.title or "",
                    "show_title": block.show_title,
                    "content": block.content or "",
                    "alignment": block.alignment,
                    "font_size": block.font_size,
                    "bold": block.bold,
                })
            config.flexsys_receipt_design = {
                "template_id": template.id,
                "name": template.name,
                "blocks": blocks,
            }

    @api.depends("flexsys_receipt_logo")
    def _compute_flexsys_has_receipt_logo(self):
        """Store whether a dedicated receipt logo is configured."""
        for config in self:
            config.flexsys_has_receipt_logo = bool(config.flexsys_receipt_logo)
