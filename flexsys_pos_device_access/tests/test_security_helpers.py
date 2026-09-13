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

    def test_pairing_and_credential_secrets_use_same_strong_primitive(self):
        model = self.env["flexsys.pos.device"]
        pairing = model._new_raw_token()
        credential = model._new_raw_token()
        self.assertNotEqual(pairing, credential)
        self.assertEqual(len(model._hash_token(pairing)), 64)
        self.assertEqual(len(model._hash_token(credential)), 64)
