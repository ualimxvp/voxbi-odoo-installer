from odoo.tests import TransactionCase


class TestSyncUserCandidates(TransactionCase):
    def setUp(self):
        super().setUp()
        self.setup = self.env["voxbi.installer.setup"].create({})
        self.internal = self.env["res.users"].create({
            "name": "Voxbi Candidate",
            "login": "voxbi_candidate@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    def test_internal_users_are_offered_and_admins_are_not(self):
        allowed = self.setup.allowed_sync_user_ids
        self.assertIn(self.internal, allowed)
        self.assertNotIn(self.env.ref("base.user_admin"), allowed)
        self.assertTrue(self.setup.has_sync_user_candidates)

    def test_admins_through_an_implied_group_are_not_offered(self):
        """Odoo 19 split res.groups.users into user_ids (explicit members only)
        and all_user_ids (members plus users that inherit the group). A user
        who is an administrator only through an implying group must still be
        excluded.
        """
        implying = self.env["res.groups"].create({
            "name": "Voxbi Implies Settings",
            "implied_ids": [(4, self.env.ref("base.group_system").id)],
        })
        indirect_admin = self.env["res.users"].create({
            "name": "Voxbi Indirect Admin",
            "login": "voxbi_indirect_admin@example.com",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id, implying.id,
            ])],
        })
        self.assertNotIn(indirect_admin, self.setup.allowed_sync_user_ids)
