import json
from unittest.mock import MagicMock, patch

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
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ) as post:
            self.setup.action_disconnect()

        url = post.call_args[0][0]
        self.assertTrue(url.endswith("/api/v1/odoo-connect/revoke"))
        self.assertFalse(self.backend.api_key)

    def test_treats_an_already_revoked_key_as_done(self):
        # Cockpit hard deletes the token, so a retry after a half-finished
        # disconnect authenticates as nobody. That must complete the cleanup,
        # not strand the customer.
        with patch.object(type(self.setup), "_post_json_with_key", return_value=(401, {})):
            self.setup.action_disconnect()

        self.assertFalse(self.backend.api_key)

    def test_keeps_the_connection_when_cockpit_refuses(self):
        with patch.object(type(self.setup), "_post_json_with_key", return_value=(500, {})):
            with self.assertRaises(UserError):
                self.setup.action_disconnect()

        self.assertEqual(self.backend.api_key, "cockpit-key")

    def test_unlinks_both_voxbi_api_keys(self):
        ApiKeys = self.env["res.users.apikeys"].sudo()
        before = ApiKeys.search_count([("name", "in", ["Voxbi installer", "Voxbi sync"])])
        self.assertGreater(before, 0)

        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        after = ApiKeys.search_count([("name", "in", ["Voxbi installer", "Voxbi sync"])])
        self.assertEqual(after, 0)

    def test_does_not_delete_the_sync_user(self):
        user = self.setup.sync_user_id
        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        self.assertTrue(user.exists())
        self.assertTrue(user.active)

    def test_clears_the_sync_user_parameter(self):
        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        self.assertFalse(
            self.env["ir.config_parameter"].sudo().get_param("voxbi.sync_user_id")
        )

    def test_keeps_call_records(self):
        model = self.env["ir.model"].sudo().search([("model", "=", "voxbi.call")], limit=1)
        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ):
            self.setup.action_disconnect()

        self.assertTrue(model.exists())

    # --- which credential actually gets sent --------------------------

    @staticmethod
    def _urlopen_response(status=200, body=None):
        response = MagicMock()
        response.getcode.return_value = status
        response.read.return_value = json.dumps(body or {}).encode("utf-8")
        return response

    def test_revoke_call_carries_the_backend_key_as_bearer_token(self):
        # Asserting the actual header, not just that a mocked method was
        # called with some url: _post_json's own _auth_headers() reads
        # cockpit_api_key only, so a shallower test could pass while the
        # real request still went out unauthenticated.
        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = self._urlopen_response(
                200, {"status": "revoked"}
            )
            self.setup.action_disconnect()

        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer cockpit-key")

    def test_authenticates_when_only_the_backend_has_a_key(self):
        # The connect-flow case that was broken: the wizard's own
        # cockpit_api_key is never populated by the browser consent flow, so
        # the backend record's key must be what is sent.
        self.assertFalse(self.setup.cockpit_api_key)

        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = self._urlopen_response(
                200, {"status": "revoked"}
            )
            self.setup.action_disconnect()

        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer cockpit-key")

    def test_falls_back_to_the_wizard_key_when_the_backend_has_none(self):
        # The older paste-a-key install flow never creates a backend key, so
        # it must still be able to authenticate a disconnect.
        self.backend.write({"api_key": False})
        self.setup.cockpit_api_key = "pasted-key"

        with patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = self._urlopen_response(
                200, {"status": "revoked"}
            )
            self.setup.action_disconnect()

        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer pasted-key")

    # --- which Cockpit the revoke is actually sent to -------------------

    def test_revoke_url_is_built_from_the_backend_cockpit_url(self):
        # The connect flow never writes voxbi.cockpit_url, only the backend
        # record's own cockpit_url, so the revoke target must come from the
        # backend, not from the system parameter.
        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ) as post:
            self.setup.action_disconnect()

        url = post.call_args[0][0]
        self.assertEqual(
            url, "https://cockpit.example.com/api/v1/odoo-connect/revoke"
        )

    def test_paste_a_key_fallback_still_uses_the_system_parameter_url(self):
        # No backend key present: the credential is the pasted one, so the
        # destination must be _cockpit_base_url(), not the backend record.
        self.backend.write({"api_key": False})
        self.setup.cockpit_api_key = "pasted-key"
        self.env["ir.config_parameter"].sudo().set_param(
            "voxbi.cockpit_url", "https://param.example.com"
        )

        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ) as post:
            self.setup.action_disconnect()

        url = post.call_args[0][0]
        self.assertEqual(
            url, "https://param.example.com/api/v1/odoo-connect/revoke"
        )

    def test_backend_url_wins_over_a_different_system_parameter(self):
        # Regression test for the bug: an instance where voxbi.cockpit_url
        # names a DIFFERENT Cockpit than the one the backend actually
        # connected to must still revoke at the backend's own Cockpit, never
        # at the one named by the system parameter.
        self.env["ir.config_parameter"].sudo().set_param(
            "voxbi.cockpit_url", "https://other-cockpit.example.com"
        )

        with patch.object(
            type(self.setup), "_post_json_with_key", return_value=(200, {"status": "revoked"})
        ) as post:
            self.setup.action_disconnect()

        url = post.call_args[0][0]
        self.assertEqual(
            url, "https://cockpit.example.com/api/v1/odoo-connect/revoke"
        )
        self.assertNotIn("other-cockpit.example.com", url)
