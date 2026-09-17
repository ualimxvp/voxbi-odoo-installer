from odoo.tests import TransactionCase


class TestConnectionState(TransactionCase):
    def setUp(self):
        super().setUp()
        self.setup = self.env["voxbi.installer.setup"].create({})
        self.env["voxbi.backend"].search([]).unlink()

    def test_not_connected_without_a_backend(self):
        self.setup.invalidate_recordset()
        self.assertFalse(self.setup.is_connected)

    def test_not_connected_when_the_backend_has_no_key(self):
        self.env["voxbi.backend"].create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.example.com",
        })
        self.setup.invalidate_recordset()
        self.assertFalse(self.setup.is_connected)

    def test_connected_when_the_backend_has_a_key(self):
        self.env["voxbi.backend"].create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.example.com",
            "api_key": "a-key",
        })
        self.setup.invalidate_recordset()
        self.assertTrue(self.setup.is_connected)
        self.assertEqual(self.setup.connected_cockpit_url, "https://cockpit.example.com")

    def test_reports_the_sync_user(self):
        self.env["voxbi.backend"].create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.example.com",
            "api_key": "a-key",
        })
        self.setup.action_create_sync_user()
        self.setup.invalidate_recordset()
        self.assertEqual(self.setup.connected_sync_user, self.setup.sync_user_id.login)
