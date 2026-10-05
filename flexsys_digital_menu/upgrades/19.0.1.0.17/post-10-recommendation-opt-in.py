import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 19.0.1.0.16 introduced recommendations with Automatic as the default.
    # 19.0.1.0.17 makes recommendations explicitly opt-in, so legacy automatic
    # values are reset to Disabled. Manual selections are preserved.
    cr.execute(
        """
        UPDATE product_template
           SET digital_menu_recommendation_mode = 'disabled'
         WHERE digital_menu_recommendation_mode = 'automatic'
        """
    )
    _logger.info("Disabled %s legacy automatic Digital Menu recommendations", cr.rowcount)
