# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import json
from datetime import timedelta
from unittest import mock

import werkzeug.utils

from odoo import fields
from odoo.tests.common import tagged

from ..controllers.connect import ConnectError, VoxbiConnectController
from .common import VoxbiConnectorCase

PATCH = "odoo.addons.voxbi_installer.controllers.connect.requests.post"


@tagged("post_install", "-at_install")
class TestConnect(VoxbiConnectorCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_str("web.base.url", "https://odoo.test")
        ICP.set_str("voxbi.cockpit_url", "https://cockpit.test")

    def _setup_record(self):
        return self.env["voxbi.installer.setup"].with_user(self.admin).create({})

    def test_connect_action_points_to_cockpit_with_redirect_uri(self):
        action = self._setup_record().action_connect_cockpit()

        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertEqual(action["target"], "self")
        self.assertTrue(
            action["url"].startswith("https://cockpit.test/odoo-connect/authorize?")
        )
        self.assertIn(
            "redirect_uri=https%3A%2F%2Fodoo.test%2Fvoxbi%2Fconnect%2Fcallback",
            action["url"],
        )
        self.assertIn("state=", action["url"])

    def test_state_is_single_use(self):
        Setup = self.env["voxbi.installer.setup"].with_user(self.admin)
        state = Setup._create_connect_state()

        self.assertTrue(Setup._consume_connect_state(state))
        self.assertFalse(Setup._consume_connect_state(state))

    def test_expired_state_fails(self):
        Setup = self.env["voxbi.installer.setup"].with_user(self.admin)
        state = Setup._create_connect_state()
        key = "voxbi.connect.state." + state
        expired = fields.Datetime.now() - timedelta(minutes=1)
        self.env["ir.config_parameter"].sudo().set_str(
            key, json.dumps({"expires_at": fields.Datetime.to_string(expired)})
        )

        self.assertFalse(Setup._consume_connect_state(state))

    def test_unknown_state_fails_without_any_http_call(self):
        with mock.patch(PATCH) as post:
            with self.assertRaises(ConnectError):
                VoxbiConnectController._complete_connect(
                    self.env(user=self.admin), "unknown-state", "some-code"
                )
        post.assert_not_called()

    def test_successful_exchange_writes_backend(self):
        Setup = self.env["voxbi.installer.setup"].with_user(self.admin)
        state = Setup._create_connect_state()

        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "api_key": "plaintext-key",
            # Cockpit's own key name; asserting the real one keeps the two
            # halves of this flow from drifting apart again.
            "cockpit_base_url": "https://cockpit.test",
            "pbx_id": "42",
        }
        with mock.patch(PATCH, return_value=response) as post:
            VoxbiConnectController._complete_connect(
                self.env(user=self.admin), state, "auth-code"
            )
        post.assert_called_once()
        # Cockpit binds the code to the redirect_uri and validates it as
        # required, so the exchange must send it back.
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["code"], "auth-code")
        self.assertTrue(sent["redirect_uri"].endswith("/voxbi/connect/callback"))

        backend = self.env["voxbi.backend"].sudo().search(
            [("api_key", "=", "plaintext-key")]
        )
        self.assertEqual(len(backend), 1)
        self.assertEqual(backend.cockpit_url, "https://cockpit.test")
        self.assertIn("42", backend.name)

    def test_callback_redirects_to_configuration_not_backend_list(self):
        # The flow continues on the Configuration wizard (pick a sync user,
        # tick consent, install). The raw backend list is not in the menu
        # and is not where the customer should land.
        Setup = self.env["voxbi.installer.setup"].with_user(self.admin)
        state = Setup._create_connect_state()

        response = mock.Mock(status_code=200)
        response.json.return_value = {
            "api_key": "plaintext-key-2",
            "cockpit_base_url": "https://cockpit.test",
            "pbx_id": "43",
        }
        config_action = self.env.ref("voxbi_installer.action_voxbi_installer_open")
        backend_action = self.env.ref("voxbi_installer.action_voxbi_backend")

        # request is a werkzeug LocalProxy with no bound request in a
        # TransactionCase, so it must be swapped in via new=... rather than
        # letting mock.patch introspect (and evaluate) the original.
        mock_request = mock.MagicMock()
        mock_request.env = self.env(user=self.admin)
        # The route wrapper coerces the endpoint's return value into a
        # werkzeug Response, so the mocked redirect() must produce one too.
        mock_request.redirect.side_effect = (
            lambda url, *a, **kw: werkzeug.utils.redirect(url)
        )
        with mock.patch(PATCH, return_value=response):
            with mock.patch(
                "odoo.addons.voxbi_installer.controllers.connect.request",
                new=mock_request,
            ):
                VoxbiConnectController().voxbi_connect_callback(
                    state=state, code="auth-code"
                )

        redirect_url = mock_request.redirect.call_args.args[0]
        self.assertEqual(redirect_url, f"/odoo/action-{config_action.id}")
        self.assertNotEqual(redirect_url, f"/odoo/action-{backend_action.id}")
