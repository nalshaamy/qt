from odoo.tests.common import TransactionCase


class TestFlexSysCommercialHardening(TransactionCase):
    def test_pairing_secret_is_not_a_stored_wizard_field(self):
        Wizard = self.env["flexsys.pos.device.token.wizard"]
        self.assertNotIn("token_value", Wizard._fields)
        self.assertIn("token_url", Wizard._fields)
        self.assertFalse(Wizard._fields["token_url"].store)

        url = "https://example.test/flexsys/pos/pair/secret-not-persisted"
        wizard = Wizard.with_context(flexsys_pairing_url=url).new({})
        self.assertEqual(wizard.token_url, url)

    def test_cashier_audit_event_is_truthful_and_legacy_value_remains_valid(self):
        event_field = self.env["flexsys.pos.device.access.log"]._fields["event"]
        selection = dict(event_field.selection)
        self.assertEqual(selection["cashier_login_reported"], "Cashier Login Reported")
        self.assertIn("pin_success", selection)


    def test_pairing_link_is_database_explicit(self):
        """Pairing URLs must target the originating DB on multi-db hosts."""
        import inspect
        source = inspect.getsource(type(self.env["flexsys.pos.device"])._build_pairing_wizard)
        self.assertIn('urlencode({"db": self.env.cr.dbname})', source)


    def test_linked_pos_user_is_required(self):
        field = self.env["flexsys.pos.device"]._fields["service_user_id"]
        self.assertTrue(field.required)


    def test_device_session_scopes_company_context(self):
        import inspect
        from ..controllers.main import FlexSysPosDeviceAccessController
        source = inspect.getsource(FlexSysPosDeviceAccessController._establish_device_session)
        self.assertIn('session_context["allowed_company_ids"] = [company_id]', source)
        self.assertIn('session_context["company_id"] = company_id', source)

    def test_linked_user_runtime_check_reads_pos_config(self):
        import inspect
        source = inspect.getsource(type(self.env["flexsys.pos.device"])._service_user_is_valid)
        self.assertIn('.read(["id", "currency_id"], load=False)', source)
