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
