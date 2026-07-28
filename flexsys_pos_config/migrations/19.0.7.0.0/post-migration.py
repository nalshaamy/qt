# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remove obsolete Receipt Studio metadata during module upgrade."""
    env = api.Environment(cr, SUPERUSER_ID, {})

    xmlids = [
        "flexsys_pos_config.view_flexsys_receipt_template_list",
        "flexsys_pos_config.view_flexsys_receipt_template_form",
        "flexsys_pos_config.view_flexsys_receipt_template_search",
        "flexsys_pos_config.view_flexsys_receipt_preview_form",
        "flexsys_pos_config.action_flexsys_receipt_templates",
        "flexsys_pos_config.action_flexsys_receipt_builder",
        "flexsys_pos_config.rule_flexsys_receipt_template_company",
        "flexsys_pos_config.rule_flexsys_receipt_block_company",
        "flexsys_pos_config.access_flexsys_receipt_template_user",
        "flexsys_pos_config.access_flexsys_receipt_template_manager",
        "flexsys_pos_config.access_flexsys_receipt_block_user",
        "flexsys_pos_config.access_flexsys_receipt_block_manager",
        "flexsys_pos_config.access_flexsys_receipt_preview_user",
        "flexsys_pos_config.group_flexsys_receipt_designer_manager",
        "flexsys_pos_config.group_flexsys_receipt_designer_user",
        "flexsys_pos_config.privilege_flexsys_receipt_studio",
        "flexsys_pos_config.module_category_flexsys_pos",
    ]

    for xmlid in xmlids:
        record = env.ref(xmlid, raise_if_not_found=False)
        if record and record.exists():
            record.unlink()

    env["ir.model.data"].search([
        ("module", "=", "flexsys_pos_config"),
        ("model", "in", [
            "flexsys.pos.receipt.template",
            "flexsys.pos.receipt.block",
            "flexsys.pos.receipt.preview",
        ]),
    ]).unlink()
