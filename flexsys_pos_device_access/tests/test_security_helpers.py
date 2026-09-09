from odoo.tests.common import TransactionCase


class TestFlexSysPosDeviceSecurityHelpers(TransactionCase):
    def test_token_entropy_and_hash(self):
        model = self.env["flexsys.pos.device"]
        raw1 = model._new_raw_token()
        raw2 = model._new_raw_token()
        self.assertGreaterEqual(len(raw1), 32)
        self.assertNotEqual(raw1, raw2)
        self.assertEqual(len(model._hash_token(raw1)), 64)
        self.assertNotIn(raw1, model._hash_token(raw1))
