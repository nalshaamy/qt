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

