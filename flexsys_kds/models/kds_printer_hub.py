# -*- coding: utf-8 -*-
from odoo import fields, models


class KdsPrinterHub(models.TransientModel):
    """Landing screen for Configuration > Printers - two "blocks"
    (Printers / Print Jobs), each a card linking to its own separate,
    full-featured page, per explicit request ("داخل FlexSys KDS نفسها،
    بتصميم مربعات/أقسام مميزة، ولكل واحدة صفحة إعداداتها الخاصة" - inside
    FlexSys KDS itself, styled as distinct boxes, each with its own
    dedicated page) - not Odoo's own General Settings app (a real
    res.config.settings integration there is a meaningfully bigger,
    riskier undertaking with its own very specific structural
    requirements, and wasn't what was actually being asked for here),
    and not the three-tabs-in-one-screen version from an earlier round
    either (that combined everything into one page; this is separate
    destinations, reached via a styled landing page instead of flat
    menu items).

    UI/DATA FIX ("Printing UI & Job History - Final Cleanup Before
    Testing"), items 1 & 2: this used to be three cards
    (Printers / Print Jobs / Reprints) - the Reprints card and its own
    action_kds_reprint_log are both removed entirely, since both were
    always the exact same kds.print.job model and list view Print Jobs
    already used; Print Jobs alone now covers the full print + reprint
    history.

    The two remaining real actions (action_kds_printer,
    action_kds_print_job) are untouched.
    """
    _name = 'kds.printer.hub'
    _description = 'FlexSys KDS Printers Hub'

    # REAL FIX (reported live: "Printing" hub's breadcrumb/header showed
    # the technical "kds.printer.hub,3" instead of a clean label, and
    # that same technical id carried over into the breadcrumb of
    # whichever page - Printers/Print Jobs/Reprints - was opened FROM
    # here, since clicking a type="action" button from within a form
    # view pushes onto the existing breadcrumb rather than replacing it).
    # Root cause: this model had no name/display_name field at all, so
    # Odoo fell back to its standard "%(model)s,%(id)s" representation
    # everywhere it needed one to show. A single static name field fixes
    # every one of those places at once - the hub's own breadcrumb, and
    # by extension every page reached from it.
    name = fields.Char(default='Printing')

