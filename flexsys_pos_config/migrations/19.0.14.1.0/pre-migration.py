# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Replace the retired bilingual report option with Auto."""
    cr.execute(
        """
        UPDATE pos_config
           SET flexsys_report_language = 'auto'
         WHERE flexsys_report_language = 'bilingual'
        """
    )
