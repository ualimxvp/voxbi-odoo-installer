# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from unittest.mock import patch

from odoo.tests.common import tagged
from odoo.tools.safe_eval import safe_eval

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
        ICP.set_param("web.base.url", "https://odoo.test")
        ICP.set_param("voxbi.cockpit_url", "https://cockpit.test")

    def setUp(self):
        super().setUp()
        self.ICP = self.env["ir.config_parameter"].sudo()
        self.ICP.set_param(SYNC_USER_PARAM, False)
        self.Setup = self.env["voxbi.installer.setup"].with_user(self.admin)

    def _install_capturing_param(self, run):
        """Run `run` with register-install mocked, returning the parameter as Cockpit would see it."""
        seen = {}

        def register_install(url, payload, *args, **kwargs):
            if url.endswith("/api/v1/odoo-installer/register-install"):
                seen["param"] = self.ICP.get_param(SYNC_USER_PARAM)
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

    def test_action_install_falls_back_to_current_user(self):
        # A sync user is mandatory: the success path revokes the installer
        # key, so installing without one would leave Cockpit on a dead key.
        setup = self.Setup.create({
            "cockpit_api_key": "cockpit-key",
            "sync_user_id": False,
        })

        _record, param = self._install_capturing_param(setup.action_install)

        self.assertEqual(setup.sync_user_id, self.admin)
        self.assertEqual(param, str(self.admin.id))

    # --- opt-in creation of the voxbi.sync user ----------------------------

    def _sync_users(self):
        return self.env["res.users"].sudo().with_context(active_test=False).search([
            ("login", "=", "voxbi.sync"),
        ])

    def _connect_backend(self):
        """What Cockpit's callback leaves behind before autostart runs."""
        self.Setup.search([]).unlink()
        self.env["voxbi.backend"].sudo().search([]).unlink()
        self.env["voxbi.backend"].sudo().create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.test",
            "api_key": "cockpit-key",
        })

    def _offered_sync_users(self):
        """The users the sync user dropdown offers to the admin.

        The dropdown searches res.users with the field's domain, as the
        logged-in admin, with the default active_test.
        """
        domain = safe_eval(self.Setup._fields["sync_user_id"].domain)
        return self.env["res.users"].with_user(self.admin).search(domain)

    def test_admin_is_offered_as_sync_user(self):
        self.assertIn(self.admin, self._offered_sync_users())

    def test_portal_and_archived_users_are_not_offered(self):
        Users = self.env["res.users"].sudo()
        portal = Users.create({
            "name": "Portal",
            "login": "portal@optin.test",
            "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        archived = Users.create({
            "name": "Archived",
            "login": "archived@optin.test",
            "active": False,
        })

        allowed = self._offered_sync_users()

        self.assertIn(self.admin, allowed)
        self.assertNotIn(portal, allowed)
        self.assertNotIn(archived, allowed)

    def test_sync_user_defaults_to_current_user(self):
        self.assertEqual(self.Setup.create({}).sync_user_id, self.admin)

    def test_autostart_without_opt_in_creates_no_user(self):
        self._connect_backend()
        self.Setup.create({})
        before = len(self._sync_users())

        record, param = self._install_capturing_param(self.Setup._autostart_install)

        self.assertEqual(len(self._sync_users()), before)
        self.assertEqual(record.sync_user_id, self.admin)
        self.assertEqual(param, str(self.admin.id))

    def test_autostart_falls_back_to_current_user_when_empty(self):
        # A wizard row saved before the opt-in existed may have no sync user.
        self._connect_backend()
        self.Setup.create({"sync_user_id": False})

        record, param = self._install_capturing_param(self.Setup._autostart_install)

        self.assertEqual(record.sync_user_id, self.admin)
        self.assertEqual(param, str(self.admin.id))

    def test_opt_in_creates_voxbi_sync_even_with_admin_selected(self):
        self._connect_backend()
        self.Setup.create({"sync_user_id": self.admin.id, "create_sync_user": True})

        record, param = self._install_capturing_param(self.Setup._autostart_install)

        self.assertEqual(record.sync_user_id.login, "voxbi.sync")
        self.assertEqual(param, str(record.sync_user_id.id))

    def test_opt_in_reuses_an_archived_voxbi_sync(self):
        self.env["res.users"].sudo().create({
            "name": "Voxbi Sync",
            "login": "voxbi.sync",
            "active": False,
        })
        self._connect_backend()
        self.Setup.create({"create_sync_user": True})

        record, _param = self._install_capturing_param(self.Setup._autostart_install)

        self.assertEqual(len(self._sync_users()), 1)
        self.assertTrue(record.sync_user_id.active)

    def test_archived_sync_user_falls_back_to_current_user(self):
        # An upgraded instance whose stored voxbi.sync was archived to drop
        # the seat: a key minted for it would never log in.
        archived = self.env["res.users"].sudo().create({
            "name": "Voxbi Sync",
            "login": "voxbi.sync",
            "active": False,
        })
        setup = self.Setup.create({"sync_user_id": archived.id})

        setup._ensure_sync_user()

        self.assertEqual(setup.sync_user_id, self.admin)

    def test_portal_sync_user_falls_back_to_current_user(self):
        portal = self.env["res.users"].sudo().create({
            "name": "Portal",
            "login": "portal-sync@optin.test",
            "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        setup = self.Setup.create({"sync_user_id": portal.id})

        setup._ensure_sync_user()

        self.assertEqual(setup.sync_user_id, self.admin)

    def test_opt_in_is_consumed_once(self):
        # Consent covers one creation. Archiving voxbi.sync afterwards must not
        # be undone (and billed again) by the next "Updates and Fixes".
        setup = self.Setup.create({"create_sync_user": True})
        setup._ensure_sync_user()
        created = setup.sync_user_id
        self.assertEqual(created.login, "voxbi.sync")
        self.assertFalse(setup.create_sync_user)

        created.active = False
        setup._ensure_sync_user()

        self.assertEqual(setup.sync_user_id, self.admin)
        self.assertFalse(created.active)

    def test_admin_sync_key_survives_installer_key_revocation(self):
        # The admin then holds both keys; revoking must take only the
        # installer one.
        setup = self.Setup.create({"sync_user_id": self.admin.id})
        setup._issue_api_key_for_current_user()
        setup._issue_api_key_for_sync_user()

        setup._revoke_installer_key()

        ApiKeys = self.env["res.users.apikeys"].sudo()
        self.assertFalse(ApiKeys.search([
            ("user_id", "=", self.admin.id),
            ("name", "=", "Voxbi installer"),
        ]))
        self.assertTrue(ApiKeys.search([
            ("user_id", "=", self.admin.id),
            ("name", "=", "Voxbi sync"),
        ]))

    def test_opt_in_never_selects_a_portal_user_holding_the_login(self):
        # A portal account cannot hold an rpc key, so the sync would die.
        self.env["res.users"].sudo().create({
            "name": "Voxbi Sync",
            "login": "voxbi.sync",
            "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        setup = self.Setup.create({"create_sync_user": True})

        setup._ensure_sync_user()

        self.assertEqual(setup.sync_user_id, self.admin)

    def test_reconnect_after_disconnect_uses_the_newly_chosen_sync_user(self):
        # Moving an existing voxbi.sync install onto the admin: Disconnect,
        # pick the admin in "Sync as", Connect again. "Updates and Fixes"
        # cannot do it, since it goes straight back to Cockpit.
        voxbi_sync = self.env["res.users"].sudo().create({
            "name": "Voxbi Sync",
            "login": "voxbi.sync",
        })
        self._connect_backend()
        setup = self.Setup.create({"sync_user_id": voxbi_sync.id})
        setup.state = "done"
        with patch.object(
            type(self.Setup), "_post_json_with_key",
            return_value=(200, {"status": "revoked"}),
        ):
            setup.action_disconnect()

        # Draft is what puts "Sync as" back on screen, still holding the choice.
        self.assertEqual(setup.state, "draft")
        self.assertEqual(setup.sync_user_id, voxbi_sync)

        setup.sync_user_id = self.admin
        self.env["voxbi.backend"].sudo().search([]).write({"api_key": "cockpit-key-2"})

        record, param = self._install_capturing_param(self.Setup._autostart_install)

        self.assertEqual(record, setup)
        self.assertEqual(record.sync_user_id, self.admin)
        self.assertEqual(param, str(self.admin.id))
        # Disconnect never removes a user; the seat stays until it is archived.
        self.assertTrue(voxbi_sync.active)
