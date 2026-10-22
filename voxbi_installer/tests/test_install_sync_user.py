# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from unittest.mock import patch

from odoo.tests.common import tagged

from .common import VoxbiConnectorCase

SYNC_USER_PARAM = "voxbi.sync_user_id"


@tagged("post_install", "-at_install")
class TestInstallSyncUser(VoxbiConnectorCase):
    """The sync user choice must be readable before Cockpit starts the install.

    integration-api reads voxbi.sync_user_id over XML-RPC while it provisions,
    to put that user into "Can Sync Voxbi Calls". If the parameter only appears
    once the install has succeeded, the grant is skipped and Cockpit is later
    swapped onto a sync user with no access to the Voxbi models.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_str("web.base.url", "https://odoo.test")
        ICP.set_str("voxbi.cockpit_url", "https://cockpit.test")

    def setUp(self):
        super().setUp()
        self.ICP = self.env["ir.config_parameter"].sudo()
        self.ICP.set_str(SYNC_USER_PARAM, False)
        self.Setup = self.env["voxbi.installer.setup"].with_user(self.admin)

    def _install_capturing_param(self, run):
        """Run `run` with register-install mocked, returning the parameter as Cockpit would see it."""
        seen = {}

        def register_install(url, payload, *args, **kwargs):
            if url.endswith("/api/v1/odoo-installer/register-install"):
                seen["param"] = self.ICP.get_str(SYNC_USER_PARAM)
            return 201, {"integration_id": 7}

        with patch.object(
            type(self.Setup), "_post_json", side_effect=register_install
        ) as post:
            record = run()

        self.assertTrue(post.called, "register-install was never posted")
        return record, seen.get("param")

    def test_sync_user_is_recorded_before_register_install(self):
        setup = self.Setup.create({"cockpit_api_key": "cockpit-key"})
        setup.action_create_sync_user()

        _record, param = self._install_capturing_param(setup.action_install)

        self.assertEqual(param, str(setup.sync_user_id.id))

    def test_connect_autostart_records_sync_user_before_register_install(self):
        # The customer's real path: Cockpit's callback stores the key on the
        # backend, then the install starts on its own.
        self.env["voxbi.backend"].sudo().search([]).unlink()
        self.env["voxbi.backend"].sudo().create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.test",
            "api_key": "cockpit-key",
        })

        record, param = self._install_capturing_param(self.Setup._autostart_install)

        self.assertTrue(record.sync_user_id)
        self.assertEqual(param, str(record.sync_user_id.id))

    def test_no_sync_user_leaves_the_parameter_unset(self):
        setup = self.Setup.create({"cockpit_api_key": "cockpit-key"})
        self.assertFalse(setup.sync_user_id)

        _record, param = self._install_capturing_param(setup.action_install)

        self.assertFalse(param)
