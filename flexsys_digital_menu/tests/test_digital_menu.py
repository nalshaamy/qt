import base64
import io

from PIL import Image

from odoo.tests.common import TransactionCase


class TestFlexSysDigitalMenu(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.template"].create({
            "name": "Spanish Latte",
            "sale_ok": True,
            "available_in_pos": True,
            "list_price": 18.0,
            "digital_menu_enabled": True,
            "digital_menu_short_description": "Espresso with milk",
            "digital_menu_calories": 230,
        })
        cls.menu = cls.env["flexsys.menu"].create({
            "name": "Main Menu",
            "slug": "main",
            "company_id": cls.env.company.id,
        })
        cls.category = cls.env["flexsys.menu.category"].create({
            "name": "Coffee",
            "menu_id": cls.menu.id,
        })
        cls.line = cls.env["flexsys.menu.product"].create({
            "menu_id": cls.menu.id,
            "product_tmpl_id": cls.product.id,
            "category_id": cls.category.id,
            "visibility": "inherit",
        })

    def test_product_default_to_menu_effective_result(self):
        self.assertTrue(self.line._effective_visibility_bool())
        self.assertEqual(self.line._get_effective_availability(), "available")
        self.assertEqual(self.line._get_effective_price(), 18.0)

    def test_menu_override_visibility(self):
        self.line.visibility = "hidden"
        self.assertFalse(self.line._effective_visibility_bool())

    def test_show_in_digital_menu_is_master_switch(self):
        self.product.digital_menu_enabled = False
        self.line.visibility = "visible"
        self.assertFalse(self.line._effective_visibility_bool())
        self.product.digital_menu_enabled = True
        self.assertTrue(self.line._effective_visibility_bool())

    def test_simple_product_fields_use_base_assignment(self):
        self.assertEqual(self.product.digital_menu_primary_menu_id, self.menu)
        self.assertEqual(self.product.digital_menu_primary_category_id, self.category)
        self.product.digital_menu_display_order = 25
        self.assertEqual(self.line.sequence, 25)

    def test_brand_generation_from_logo(self):
        image = Image.new("RGB", (48, 48), (20, 90, 65))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.menu.logo = base64.b64encode(buffer.getvalue())
        self.menu.action_generate_brand()
        self.assertTrue(self.menu.theme_id)
        self.assertRegex(self.menu.theme_id.primary, r"^#[0-9A-F]{6}$")
        self.assertTrue(self.menu.theme_id.button_text in ("#FFFFFF", "#17201D"))

    def test_qr_generation(self):
        self.menu.action_generate_qr()
        self.assertTrue(self.menu.qr_ids)
        self.assertTrue(self.menu.qr_ids[0].png)
        self.assertTrue(self.menu.qr_ids[0].svg)

    def test_public_payload_has_public_keys_not_record_ids(self):
        self.menu.state = "published"
        payload = self.menu._public_payload(requested_lang="en")
        self.assertEqual(payload["menu"]["slug"], "main")
        self.assertEqual(payload["menu"]["company_name"], self.env.company.name)
        self.assertTrue(payload["products"])
        product = payload["products"][0]
        self.assertIn("key", product)
        self.assertNotIn("id", product)
        self.assertEqual(product["name"], "Spanish Latte")
    def test_public_payload_keeps_full_description(self):
        self.menu.state = "published"
        full_description = "Espresso with milk and a long description that must remain complete in product details."
        self.product.digital_menu_short_description = full_description
        payload = self.menu._public_payload(requested_lang="en")
        self.assertEqual(payload["products"][0]["description"], full_description)

    def test_standard_badges_follow_public_language(self):
        self.menu.state = "published"
        self.product.digital_menu_default_badge = "chef"
        en_payload = self.menu._public_payload(requested_lang="en")
        ar_payload = self.menu._public_payload(requested_lang="ar")
        self.assertEqual(en_payload["products"][0]["badge"], "Chef Recommendation")
        self.assertEqual(ar_payload["products"][0]["badge"], "توصية الشيف")

    def test_custom_badge_uses_explicit_ar_en_values(self):
        self.menu.state = "published"
        self.product.write({
            "digital_menu_default_badge": "custom",
            "digital_menu_custom_badge_ar": "اختيارنا",
            "digital_menu_custom_badge_en": "Our Pick",
        })
        en_payload = self.menu._public_payload(requested_lang="en")
        ar_payload = self.menu._public_payload(requested_lang="ar")
        self.assertEqual(en_payload["products"][0]["badge"], "Our Pick")
        self.assertEqual(ar_payload["products"][0]["badge"], "اختيارنا")
    def test_public_payload_uses_brand_name_with_company_fallback(self):
        self.menu.state = "published"
        payload = self.menu._public_payload(requested_lang="en")
        self.assertEqual(payload["menu"]["brand_name"], self.env.company.name)
        self.menu.brand_name = "QTCafe"
        payload = self.menu._public_payload(requested_lang="en")
        self.assertEqual(payload["menu"]["brand_name"], "QTCafe")

    def test_important_badge_requests_subtle_pulse(self):
        self.menu.state = "published"
        self.product.digital_menu_default_badge = "best_seller"
        payload = self.menu._public_payload(requested_lang="en")
        product = payload["products"][0]
        self.assertEqual(product["badge_type"], "best_seller")
        self.assertTrue(product["badge_pulse"])

    def test_text_color_overrides_are_exported_as_css_variables(self):
        self.menu.header_text_color_override = "#FFFFFF"
        self.menu.footer_text_color_override = "#111111"
        variables = self.menu.css_variables()
        self.assertIn("--menu-hero-text:#FFFFFF", variables)
        self.assertIn("--menu-footer-text:#111111", variables)

    def test_brand_navigation_hides_unpublished_pages(self):
        self.menu.state = "published"
        page = self.env["flexsys.brand.page"].create({
            "menu_id": self.menu.id,
            "name": "About",
            "slug": "about",
            "page_type": "about",
            "is_published": False,
        })
        navigation = self.menu._public_navigation("en")
        self.assertEqual([item["key"] for item in navigation], ["menu"])
        page.is_published = True
        navigation = self.menu._public_navigation("en")
        self.assertEqual([item["key"] for item in navigation], ["menu", "page:about"])
        self.assertEqual(navigation[1]["label"], "About")

    def test_public_payload_exposes_brand_navigation(self):
        self.menu.state = "published"
        self.env["flexsys.brand.page"].create({
            "menu_id": self.menu.id,
            "name": "Branches",
            "slug": "branches",
            "page_type": "branches",
            "is_published": True,
        })
        payload = self.menu._public_payload(requested_lang="en")
        navigation = payload["menu"]["navigation"]
        self.assertEqual(navigation[0]["key"], "menu")
        self.assertTrue(navigation[0]["active"])
        self.assertEqual(navigation[1]["url"], "/menu/main/page/branches?lang=en")

    def test_brand_page_public_url_uses_menu_public_url(self):
        page = self.env["flexsys.brand.page"].create({
            "menu_id": self.menu.id,
            "name": "About",
            "slug": "about",
        })
        self.assertTrue(page.public_url.endswith("/menu/main/page/about"))

    def test_menu_layout_is_exposed_to_public_frontend(self):
        self.menu.state = "published"
        self.menu.layout_style = "compact"
        payload = self.menu._public_payload(requested_lang="en")
        self.assertEqual(payload["menu"]["layout"], "compact")

    def test_active_offer_is_exposed_without_parallel_pricing_engine(self):
        self.menu.state = "published"
        offer = self.env["flexsys.menu.offer"].create({
            "menu_id": self.menu.id,
            "name": "Coffee Pick",
            "product_ids": [(6, 0, [self.product.id])],
            "is_published": True,
        })
        payload = self.menu._public_payload(requested_lang="en")
        self.assertEqual(len(payload["offers"]), 1)
        self.assertEqual(payload["offers"][0]["key"], offer.public_key)
        self.assertEqual(payload["offers"][0]["product_keys"], [self.line.public_key])
        self.assertIsNone(payload["offers"][0]["price"])

    def test_analytics_menu_view_is_deduplicated_per_session_and_day(self):
        self.menu.state = "published"
        Event = self.env["flexsys.menu.analytics.event"]
        payload = {"language": "en", "session": "anonymous-test-session"}
        Event.record_public_event(self.menu, "menu_view", payload)
        Event.record_public_event(self.menu, "menu_view", payload)
        self.assertEqual(Event.search_count([
            ("menu_id", "=", self.menu.id), ("event_type", "=", "menu_view")
        ]), 1)

    def test_branches_page_can_be_created_without_publishing_it(self):
        action = self.menu.action_create_branches_page()
        page = self.env["flexsys.brand.page"].browse(action["res_id"])
        self.assertEqual(page.page_type, "branches")
        self.assertFalse(page.is_published)

    def test_active_offer_is_added_to_brand_navigation(self):
        self.menu.state = "published"
        self.env["flexsys.menu.offer"].create({
            "menu_id": self.menu.id,
            "name": "Weekend Offer",
            "product_ids": [(6, 0, [self.product.id])],
            "is_published": True,
        })
        navigation = self.menu._public_navigation("en")
        self.assertEqual(navigation[0]["key"], "menu")
        self.assertEqual(navigation[1]["key"], "offers")
        self.assertEqual(navigation[1]["url"], "/menu/main/offers?lang=en")
    def test_product_without_image_uses_brand_logo_route(self):
        self.menu.state = "published"
        image = Image.new("RGB", (32, 32), (20, 90, 65))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        self.menu.logo = base64.b64encode(buffer.getvalue())
        self.product.image_1920 = False
        self.product.digital_menu_image = False
        payload = self.menu._public_payload(requested_lang="en")
        self.assertTrue(payload["products"][0]["image_url"].endswith(f"/product/{self.line.public_key}/image"))

