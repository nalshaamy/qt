import base64
import io
import json
from urllib.parse import urlparse

from PIL import Image

from odoo import http
from odoo.http import request


class FlexSysDigitalMenuController(http.Controller):

    @staticmethod
    def _current_host():
        return (request.httprequest.host or "").lower().rstrip("/")

    def _find_menu(self, slug):
        candidates = request.env["flexsys.menu"].sudo().search([
            ("slug", "=", slug),
            ("state", "=", "published"),
        ])
        if not candidates:
            return candidates
        host = self._current_host()
        exact = candidates.filtered(lambda menu: (menu.public_domain or "").lower() == host)
        if exact:
            return exact[:1]
        no_domain = candidates.filtered(lambda menu: not menu.public_domain)
        if len(no_domain) == 1:
            return no_domain
        return request.env["flexsys.menu"]

    @staticmethod
    def _image_content_type(raw):
        try:
            fmt = Image.open(io.BytesIO(raw)).format
            return {
                "PNG": "image/png",
                "JPEG": "image/jpeg",
                "WEBP": "image/webp",
                "GIF": "image/gif",
            }.get(fmt, "application/octet-stream")
        except Exception:
            return "application/octet-stream"

    def _binary_response(self, value, content_type=None, filename=None, cache_seconds=300):
        if not value:
            return request.not_found()
        raw = base64.b64decode(value)
        cache_header = (
            "private, no-store" if not cache_seconds
            else f"public, max-age={cache_seconds}, stale-while-revalidate=60"
        )
        headers = [
            ("Content-Type", content_type or self._image_content_type(raw)),
            ("Cache-Control", cache_header),
            ("X-Content-Type-Options", "nosniff"),
        ]
        if filename:
            safe_filename = str(filename).replace("\r", "").replace("\n", "").replace(chr(34), "")
            headers.append(("Content-Disposition", f'inline; filename="{safe_filename}"'))
        return request.make_response(raw, headers=headers)

    @staticmethod
    def _format_public_amount(amount, currency):
        if amount is None:
            return ""
        decimals = int(currency.decimal_places if currency else 2)
        number = f"{float(amount):,.{decimals}f}"
        if decimals:
            number = number.rstrip("0").rstrip(".")
        symbol = (currency.symbol or currency.name) if currency else "SAR"
        if currency and currency.position == "before":
            return f"{symbol} {number}"
        return f"{number} {symbol}"

    def _offers_page_values(self, menu, requested_lang=None, preview=False):
        lang_code, language = menu._language_code(requested_lang)
        menu = menu.with_context(lang=lang_code)
        payload = menu._public_payload(requested_lang=language, preview=preview)
        currency = menu.currency_id
        offers = []
        for item in payload.get("offers", []):
            offer = dict(item)
            offer["display_price"] = self._format_public_amount(offer.get("price"), currency)
            offer["display_original_price"] = self._format_public_amount(offer.get("original_price"), currency)
            offer["action_url"] = (
                f"/digital-menu/preview-content/{menu.id}?lang={language}&offer={offer['key']}"
                if preview else f"/menu/{menu.slug}?lang={language}&offer={offer['key']}"
            )
            offers.append(offer)
        return {
            "menu": menu,
            "offers": offers,
            "css_variables": menu.css_variables(),
            "seo_title": ("العروض" if language == "ar" else "Offers") + " — " + (menu.brand_name or menu.company_id.name or menu.name),
            "logo_url": f"/menu/{menu.slug}/logo" if menu.logo else "",
            "language": language,
            "navigation": menu._public_navigation(language, active_key="offers", preview=preview),
        }

    @http.route("/menu/<string:slug>", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def public_menu(self, slug, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        values = {
            "menu": menu,
            "css_variables": menu.css_variables(),
            "seo_title": menu.seo_title or menu.brand_name or menu.company_id.name or menu.name,
            "data_url": f"/menu/{menu.slug}/data",
            "logo_url": f"/menu/{menu.slug}/logo" if menu.logo else "",
            "language": menu.default_language,
            "navigation": menu._public_navigation(menu.default_language, active_key="menu"),
        }
        response = request.render("flexsys_digital_menu.public_menu_page", values)
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @http.route("/menu/<string:slug>/offers", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def public_offers(self, slug, lang=None, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        values = self._offers_page_values(menu, requested_lang=lang, preview=False)
        response = request.render("flexsys_digital_menu.public_offers_page", values)
        response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @http.route("/menu/<string:slug>/page/<string:page_slug>", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def public_brand_page(self, slug, page_slug, lang=None, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        lang_code, language = menu._language_code(lang)
        menu = menu.with_context(lang=lang_code)
        page = request.env["flexsys.brand.page"].sudo().with_company(menu.company_id).with_context(lang=lang_code).search([
            ("menu_id", "=", menu.id),
            ("slug", "=", page_slug),
            ("is_published", "=", True),
        ], limit=1)
        if not page:
            return request.not_found()
        values = {
            "menu": menu,
            "page": page,
            "css_variables": menu.css_variables(),
            "seo_title": page.seo_title or page.title or page.name or menu.brand_name or menu.company_id.name,
            "logo_url": f"/menu/{menu.slug}/logo" if menu.logo else "",
            "language": language,
            "navigation": menu._public_navigation(language, active_key=f"page:{page.slug}"),
            "branches": menu._public_branches_payload(language) if page.page_type == "branches" else [],
        }
        response = request.render("flexsys_digital_menu.public_brand_page", values)
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    def _get_preview_menu(self, menu_id):
        menu = request.env["flexsys.menu"].browse(menu_id).exists()
        if not menu:
            return menu
        if not request.env.user.has_group("flexsys_digital_menu.group_digital_menu_user"):
            return request.env["flexsys.menu"]
        if menu.company_id not in request.env.companies:
            return request.env["flexsys.menu"]
        return menu

    @http.route("/digital-menu/preview/<int:menu_id>", type="http", auth="user", methods=["GET"], sitemap=False)
    def backend_preview(self, menu_id, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        return request.render("flexsys_digital_menu.backend_preview_page", {
            "menu": menu,
            "content_url": f"/digital-menu/preview-content/{menu.id}",
        })

    @http.route("/digital-menu/preview-content/<int:menu_id>", type="http", auth="user", methods=["GET"], sitemap=False)
    def backend_preview_content(self, menu_id, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        return request.render("flexsys_digital_menu.public_menu_page", {
            "menu": menu,
            "css_variables": menu.css_variables(),
            "seo_title": menu.seo_title or menu.brand_name or menu.company_id.name or menu.name,
            "data_url": f"/digital-menu/preview-data/{menu.id}",
            "logo_url": f"/digital-menu/preview-asset/{menu.id}/logo" if menu.logo else "",
            "language": menu.default_language,
            "navigation": menu._public_navigation(menu.default_language, active_key="menu", preview=True),
        })

    @http.route("/digital-menu/preview-offers/<int:menu_id>", type="http", auth="user", methods=["GET"], sitemap=False)
    def backend_preview_offers(self, menu_id, lang=None, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        return request.render(
            "flexsys_digital_menu.public_offers_page",
            self._offers_page_values(menu, requested_lang=lang, preview=True),
        )

    @http.route("/digital-menu/preview-asset/<int:menu_id>/logo", type="http", auth="user", methods=["GET"], sitemap=False)
    def preview_logo(self, menu_id, **kwargs):
        menu = self._get_preview_menu(menu_id)
        return self._binary_response(menu.logo, cache_seconds=0) if menu else request.not_found()

    @http.route("/digital-menu/preview-asset/<int:menu_id>/hero", type="http", auth="user", methods=["GET"], sitemap=False)
    def preview_hero(self, menu_id, **kwargs):
        menu = self._get_preview_menu(menu_id)
        return self._binary_response(menu.hero_image, cache_seconds=0) if menu else request.not_found()

    @http.route("/digital-menu/preview-asset/<int:menu_id>/category/<string:public_key>/image", type="http", auth="user", methods=["GET"], sitemap=False)
    def preview_category_image(self, menu_id, public_key, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        category = request.env["flexsys.menu.category"].search([("menu_id", "=", menu.id), ("public_key", "=", public_key)], limit=1)
        return self._binary_response(category.image, cache_seconds=0) if category else request.not_found()

    @http.route("/digital-menu/preview-asset/<int:menu_id>/product/<string:public_key>/image", type="http", auth="user", methods=["GET"], sitemap=False)
    def preview_product_image(self, menu_id, public_key, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        line = request.env["flexsys.menu.product"].search([("menu_id", "=", menu.id), ("public_key", "=", public_key)], limit=1)
        if not line:
            return request.not_found()
        return self._binary_response(line._effective_image_source() or menu.logo or menu.company_id.logo, cache_seconds=0)

    @http.route("/digital-menu/preview-asset/<int:menu_id>/offer/<string:public_key>/image", type="http", auth="user", methods=["GET"], sitemap=False)
    def preview_offer_image(self, menu_id, public_key, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        offer = request.env["flexsys.menu.offer"].search([("menu_id", "=", menu.id), ("public_key", "=", public_key)], limit=1)
        return self._binary_response(offer.image, cache_seconds=0) if offer else request.not_found()

    @http.route(
        "/digital-menu/preview-asset/<int:menu_id>/banner/<string:public_key>/<string:variant>",
        type="http", auth="user", methods=["GET"], sitemap=False,
    )
    def preview_banner_media(self, menu_id, public_key, variant="media", **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.not_found()
        banner = request.env["flexsys.menu.banner"].search([
            ("menu_id", "=", menu.id), ("public_key", "=", public_key)
        ], limit=1)
        if not banner:
            return request.not_found()
        mobile = variant == "mobile" and bool(banner.mobile_media)
        value = banner.mobile_media if mobile else banner.desktop_media
        filename = banner.mobile_filename if mobile else banner.desktop_filename
        return self._binary_response(
            value, content_type=banner.media_mimetype(mobile=mobile), filename=filename or None, cache_seconds=0
        )

    @http.route("/digital-menu/preview-data/<int:menu_id>", type="http", auth="user", methods=["GET"], csrf=False, sitemap=False)
    def backend_preview_data(self, menu_id, lang=None, branch=None, **kwargs):
        menu = self._get_preview_menu(menu_id)
        if not menu:
            return request.make_json_response({"error": "not_found"}, status=404)
        return request.make_json_response(
            menu._public_payload(requested_lang=lang, branch_key=branch, preview=True),
            headers=[("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")],
        )

    @http.route("/menu/<string:slug>/data", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def public_menu_data(self, slug, lang=None, branch=None, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.make_json_response({"error": "not_found"}, status=404)
        payload = menu._public_payload(requested_lang=lang, branch_key=branch)
        return request.make_json_response(
            payload,
            headers=[
                ("Cache-Control", "no-store, max-age=0"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )

    @http.route("/menu/<string:slug>/logo", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def menu_logo(self, slug, **kwargs):
        menu = self._find_menu(slug)
        return self._binary_response(menu.logo, cache_seconds=3600) if menu else request.not_found()

    @http.route("/menu/<string:slug>/hero", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def menu_hero(self, slug, **kwargs):
        menu = self._find_menu(slug)
        return self._binary_response(menu.hero_image, cache_seconds=3600) if menu else request.not_found()

    @http.route(
        "/menu/<string:slug>/category/<string:public_key>/image",
        type="http", auth="public", methods=["GET"], csrf=False, sitemap=False,
    )
    def category_image(self, slug, public_key, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        category = request.env["flexsys.menu.category"].sudo().search([
            ("menu_id", "=", menu.id), ("public_key", "=", public_key), ("visible", "=", True)
        ], limit=1)
        return self._binary_response(category.image, cache_seconds=1800) if category else request.not_found()

    @http.route(
        "/menu/<string:slug>/product/<string:public_key>/image",
        type="http", auth="public", methods=["GET"], csrf=False, sitemap=False,
    )
    def product_image(self, slug, public_key, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        line = request.env["flexsys.menu.product"].sudo().search([
            ("menu_id", "=", menu.id), ("public_key", "=", public_key)
        ], limit=1)
        if not line:
            return request.not_found()
        return self._binary_response(line._effective_image_source() or menu.logo or menu.company_id.logo, cache_seconds=900)

    @http.route(
        "/menu/<string:slug>/offer/<string:public_key>/image",
        type="http", auth="public", methods=["GET"], csrf=False, sitemap=False,
    )
    def offer_image(self, slug, public_key, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        offer = request.env["flexsys.menu.offer"].sudo().search([
            ("menu_id", "=", menu.id), ("public_key", "=", public_key), ("is_published", "=", True)
        ], limit=1)
        return self._binary_response(offer.image, cache_seconds=900) if offer else request.not_found()

    @http.route(
        "/menu/<string:slug>/banner/<string:public_key>/<string:variant>",
        type="http", auth="public", methods=["GET"], csrf=False, sitemap=False,
    )
    def banner_media(self, slug, public_key, variant="media", **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        banner = request.env["flexsys.menu.banner"].sudo().search([
            ("menu_id", "=", menu.id), ("public_key", "=", public_key), ("is_published", "=", True)
        ], limit=1)
        if not banner or not banner.is_active_now(preview=False):
            return request.not_found()
        mobile = variant == "mobile" and bool(banner.mobile_media)
        value = banner.mobile_media if mobile else banner.desktop_media
        filename = banner.mobile_filename if mobile else banner.desktop_filename
        return self._binary_response(
            value, content_type=banner.media_mimetype(mobile=mobile), filename=filename or None, cache_seconds=900
        )

    @http.route(
        "/menu/<string:slug>/branch/<string:branch_key>/image",
        type="http", auth="public", methods=["GET"], csrf=False, sitemap=False,
    )
    def branch_image(self, slug, branch_key, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        branch = menu.resolve_branch_key(branch_key)
        if not branch:
            return request.not_found()
        return self._binary_response(branch.digital_menu_image, cache_seconds=1800)

    @http.route("/menu/<string:slug>/event", type="http", auth="public", methods=["POST"], csrf=False, sitemap=False)
    def public_analytics_event(self, slug, **kwargs):
        menu = self._find_menu(slug)
        if not menu or not menu.analytics_enabled:
            return request.make_json_response({"ok": False}, status=404 if not menu else 200)
        if (request.httprequest.content_length or 0) > 4096:
            return request.make_json_response({"ok": False}, status=413)
        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        event_type = (payload.get("event_type") or "")[:32]
        request.env["flexsys.menu.analytics.event"].sudo().record_public_event(menu, event_type, payload)
        return request.make_json_response({"ok": True}, headers=[("Cache-Control", "no-store")])

    @http.route("/menu/<string:slug>/qr.png", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def menu_qr_png(self, slug, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        if not menu.qr_ids:
            menu.action_generate_qr()
        qr = menu.qr_ids[:1]
        return self._binary_response(qr.png, content_type="image/png", filename=f"{slug}-qr.png", cache_seconds=3600)

    @http.route("/menu/<string:slug>/qr.svg", type="http", auth="public", methods=["GET"], csrf=False, sitemap=False)
    def menu_qr_svg(self, slug, **kwargs):
        menu = self._find_menu(slug)
        if not menu:
            return request.not_found()
        if not menu.qr_ids:
            menu.action_generate_qr()
        qr = menu.qr_ids[:1]
        return self._binary_response(qr.svg, content_type="image/svg+xml", filename=f"{slug}-qr.svg", cache_seconds=3600)
