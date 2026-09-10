# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests.common import tagged

from .common import VoxbiConnectorCase


@tagged("post_install", "-at_install")
class TestAccess(VoxbiConnectorCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        user_group = cls.env.ref("voxbi_installer.group_voxbi_user")
        manager_group = cls.env.ref("voxbi_installer.group_voxbi_manager")

        cls.user_a = cls.env["res.users"].create(
            {
                "name": "Voxbi User A",
                "login": "voxbi_user_a",
                "email": "voxbi_user_a@example.com",
                "groups_id": [(6, 0, [user_group.id])],
            }
        )
        cls.user_b = cls.env["res.users"].create(
            {
                "name": "Voxbi User B",
                "login": "voxbi_user_b",
                "email": "voxbi_user_b@example.com",
                "groups_id": [(6, 0, [user_group.id])],
            }
        )
        cls.manager = cls.env["res.users"].create(
            {
                "name": "Voxbi Manager",
                "login": "voxbi_manager",
                "email": "voxbi_manager@example.com",
                "groups_id": [(6, 0, [manager_group.id])],
            }
        )

        cls.call_a = cls.env["voxbi.call"].create(
            {
                "backend_id": cls.backend.id,
                "external_id": "cl_access_a",
                "phone": "+352661111111",
                "user_id": cls.user_a.id,
            }
        )
        cls.call_b = cls.env["voxbi.call"].create(
            {
                "backend_id": cls.backend.id,
                "external_id": "cl_access_b",
                "phone": "+352661222222",
                "user_id": cls.user_b.id,
            }
        )
        cls.call_participant = cls.env["voxbi.call"].create(
            {
                "backend_id": cls.backend.id,
                "external_id": "cl_access_participant",
                "phone": "+352661333333",
                "user_id": cls.user_b.id,
                "participant_ids": [
                    (0, 0, {"external_id": "pt_access", "user_id": cls.user_a.id}),
                ],
            }
        )

    def _visible(self, user, call):
        # exists() is a raw DB check and ignores ir.rule; search() enforces
        # it, so search is what actually proves visibility.
        found = self.env["voxbi.call"].with_user(user).search(
            [("id", "=", call.id)]
        )
        return bool(found)

    def test_user_sees_own_call(self):
        self.assertTrue(self._visible(self.user_a, self.call_a))

    def test_user_does_not_see_another_users_call(self):
        self.assertFalse(self._visible(self.user_a, self.call_b))

    def test_user_sees_call_where_they_are_a_participant(self):
        self.assertTrue(self._visible(self.user_a, self.call_participant))

    def test_manager_sees_all_calls(self):
        self.assertTrue(self._visible(self.manager, self.call_a))
        self.assertTrue(self._visible(self.manager, self.call_b))
        self.assertTrue(self._visible(self.manager, self.call_participant))
