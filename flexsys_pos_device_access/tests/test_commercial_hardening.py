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


    def test_linked_pos_user_is_required(self):
        field = self.env["flexsys.pos.device"]._fields["service_user_id"]
        self.assertTrue(field.required)


    def test_device_session_scopes_company_context(self):
        import inspect
        from ..controllers.main import FlexSysPosDeviceAccessController
        source = inspect.getsource(FlexSysPosDeviceAccessController._establish_device_session)
        self.assertIn('session_context["allowed_company_ids"] = [company_id]', source)
        self.assertIn('session_context["company_id"] = company_id', source)

    def test_linked_user_runtime_check_loads_full_pos_config_payload(self):
        import inspect
        source = inspect.getsource(type(self.env["flexsys.pos.device"])._service_user_is_valid)
        self.assertIn('._load_pos_data_search_read({}, config)', source)
        self.assertIn('with_context(allowed_company_ids=[company.id])', source)


    def test_pairing_link_hides_db_on_unique_hostname(self):
        import inspect
        source = inspect.getsource(type(self.env["flexsys.pos.device"])._build_pairing_wizard)
        self.assertIn('if visible_dbs == [dbname]:', source)
        self.assertIn('/web/login#flexsys_pair=', source)

    def test_pairing_link_uses_db_fallback_on_shared_hostname(self):
        import inspect
        source = inspect.getsource(type(self.env["flexsys.pos.device"])._build_pairing_wizard)
        self.assertIn('urlencode({"db": dbname})', source)
        self.assertIn('/web/login?{query}#flexsys_pair=', source)
