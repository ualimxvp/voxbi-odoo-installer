from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestDisconnect(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["voxbi.backend"].search([]).unlink()
        self.backend = self.env["voxbi.backend"].create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.example.com",
            "api_key": "cockpit-key",
        })
        self.setup = self.env["voxbi.installer.setup"].create({})
        self.setup.action_create_sync_user()
        self.setup._issue_api_key_for_sync_user()

    def test_revokes_at_cockpit_before_clearing_locally(self):
        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "revoked"})
        ) as post:
            self.setup.action_disconnect()

        url = post.call_args[0][0]
        self.assertTrue(url.endswith("/api/v1/odoo-connect/revoke"))
        self.assertFalse(self.backend.api_key)

    def test_treats_an_already_revoked_key_as_done(self):
        # Cockpit hard deletes the token, so a retry after a half-finished
        # disconnect authenticates as nobody. That must complete the cleanup,
        # not strand the customer.
        with patch.object(type(self.setup), "_post_json", return_value=(401, {})):
            self.setup.action_disconnect()

        self.assertFalse(self.backend.api_key)

    def test_keeps_the_connection_when_cockpit_refuses(self):
        with patch.object(type(self.setup), "_post_json", return_value=(500, {})):
            with self.assertRaises(UserError):
                self.setup.action_disconnect()

        self.assertEqual(self.backend.api_key, "cockpit-key")

    def test_unlinks_both_voxbi_api_keys(self):
        ApiKeys = self.env["res.users.apikeys"].sudo()
        before = ApiKeys.search_count([("name", "in", ["Voxbi installer", "Voxbi sync"])])
        self.assertGreater(before, 0)

        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        after = ApiKeys.search_count([("name", "in", ["Voxbi installer", "Voxbi sync"])])
        self.assertEqual(after, 0)

    def test_does_not_delete_the_sync_user(self):
        user = self.setup.sync_user_id
        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        self.assertTrue(user.exists())
        self.assertTrue(user.active)

    def test_clears_the_sync_user_parameter(self):
        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        self.assertFalse(
            self.env["ir.config_parameter"].sudo().get_param("voxbi.sync_user_id")
        )

    def test_keeps_call_records(self):
        model = self.env["ir.model"].sudo().search([("model", "=", "voxbi.call")], limit=1)
        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        self.assertTrue(model.exists())
