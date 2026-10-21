"""Read-only, POS-user-scoped receipt configuration endpoint.

No POS data loader, product pricing, payments, or currency records are modified.
"""
import base64

from odoo import http
from odoo.http import request
from werkzeug.exceptions import Forbidden, NotFound


class FlexsysReceiptSettings(http.Controller):

    @http.route(
        "/flexsys_pos_receipt/settings/<int:config_id>",
        type="http", auth="user", methods=["GET"], website=False,
    )
    def receipt_settings(self, config_id, **kwargs):
        user = request.env.user
        if not (user.has_group("point_of_sale.group_pos_user")
                or user.has_group("point_of_sale.group_pos_manager")):
            raise Forbidden()
        config = request.env["pos.config"].sudo().browse(config_id).exists()
        if not config:
            raise NotFound()
        if config.company_id.id not in user.company_ids.ids:
            raise Forbidden()

        def image_data(image):
            if not image:
                return ""
            # fields.Image returns a base64-encoded bytes value for authenticated reads.
            encoded = image.decode("ascii") if isinstance(image, bytes) else str(image)
            # Require a bounded encoded length even if an image was stored before resizing.
            if len(encoded) > 1_200_000:
                return ""
            try:
                prefix = base64.b64decode(encoded[:48])
            except (ValueError, TypeError):
                return ""
            if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
                mimetype = "image/png"
            elif prefix.startswith(b"\xff\xd8\xff"):
                mimetype = "image/jpeg"
            elif prefix.startswith(b"RIFF") and b"WEBP" in prefix[:16]:
                mimetype = "image/webp"
            else:
                return ""
            return f"data:{mimetype};base64,{encoded}"

        result = {
            "show_company_footer": bool(config.flexsys_show_company_footer),
            "currency_symbol_mode": config.flexsys_currency_symbol_mode or "new",
            "header_enabled": bool(config.flexsys_show_header_image),
            "header_position": config.flexsys_header_image_position or "above",
            "header_image": image_data(config.flexsys_header_image) if config.flexsys_show_header_image else "",
            "footer_enabled": bool(config.flexsys_show_footer_image),
            "footer_image": image_data(config.flexsys_footer_image) if config.flexsys_show_footer_image else "",
            "thank_you_enabled": bool(config.flexsys_show_thank_you),
            "thank_you_ar": config.flexsys_thank_you_ar or "",
            "thank_you_en": config.flexsys_thank_you_en or "",
        }
        response = request.make_json_response(result)
        response.headers["Cache-Control"] = "no-store, private"
        return response
