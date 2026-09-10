# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests.common import tagged

from ..components.importer import VoxbiCallImporter
from .common import VoxbiConnectorCase, call_payload


@tagged("post_install", "-at_install")
class TestTombstone(VoxbiConnectorCase):
    def _import(self, payload):
        return VoxbiCallImporter(self.env, self.backend).run(payload)

    def _count(self):
        return self.env["voxbi.call"].search_count(
            [("backend_id", "=", self.backend.id)]
        )

    def test_tombstone_removes_an_existing_call(self):
        self._import(call_payload())
        self.assertEqual(self._count(), 1)
        result = self._import({"id": "cl_01J8XQ", "deleted": True})
        self.assertFalse(result)
        self.assertEqual(self._count(), 0)

    def test_tombstone_for_an_unknown_call_is_a_no_op(self):
        result = self._import({"id": "cl_never_seen", "deleted": True})
        self.assertFalse(result)
        self.assertEqual(self._count(), 0)
