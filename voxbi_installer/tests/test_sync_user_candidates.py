from odoo.tests import TransactionCase
from odoo.tools.safe_eval import safe_eval


class TestSyncUserCandidates(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal = self.env["res.users"].create({
            "name": "Voxbi Candidate",
            "login": "voxbi_candidate@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    def test_internal_users_and_admins_are_offered(self):
        """Administrators are offered too, so syncing never forces a new seat."""
        Setup = self.env["voxbi.installer.setup"]
        domain = safe_eval(Setup._fields["sync_user_id"].domain)
        offered = self.env["res.users"].search(domain)
        self.assertIn(self.internal, offered)
        self.assertIn(self.env.ref("base.user_admin"), offered)
