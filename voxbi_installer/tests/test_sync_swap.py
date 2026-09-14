from unittest.mock import patch

from odoo.tests import TransactionCase


class TestSyncSwap(TransactionCase):
    def setUp(self):
        super().setUp()
        self.setup = self.env["voxbi.installer.setup"].create({})
        self.setup.action_create_sync_user()

    def test_swap_is_posted_once_the_install_succeeds(self):
        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "ok"})
        ) as post:
            self.setup._swap_to_sync_user()

        url, payload = post.call_args[0][0], post.call_args[0][1]
        self.assertTrue(url.endswith("/api/v1/odoo-installer/swap-to-sync-user"))
        self.assertEqual(payload["sync_user"], self.setup.sync_user_id.login)
        self.assertTrue(payload["sync_key"])
        self.assertEqual(payload["sync_uid"], self.setup.sync_user_id.id)

    def test_no_swap_without_a_sync_user(self):
        self.setup.sync_user_id = False
        with patch.object(type(self.setup), "_post_json") as post:
            self.setup._swap_to_sync_user()
        post.assert_not_called()

    def test_swap_is_not_repeated(self):
        with patch.object(
            type(self.setup), "_post_json", return_value=(200, {"status": "ok"})
        ) as post:
            self.setup._swap_to_sync_user()
            self.setup._swap_to_sync_user()
        self.assertEqual(post.call_count, 1)
