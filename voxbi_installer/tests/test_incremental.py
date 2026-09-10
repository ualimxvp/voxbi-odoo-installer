# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from unittest import mock

from odoo.tests.common import tagged

from .common import VoxbiConnectorCase, call_payload

ADAPTER = (
    "odoo.addons.voxbi_installer.components.adapter.VoxbiAdapter.fetch_since"
)


@tagged("post_install", "-at_install")
class TestIncremental(VoxbiConnectorCase):
    def _count(self):
        return self.env["voxbi.call"].search_count(
            [("backend_id", "=", self.backend.id)]
        )

    def test_first_run_imports_and_advances_the_cursor(self):
        page = {
            "calls": [call_payload()],
            "next_since": "2026-09-10T08:04:11Z",
            "has_more": False,
        }
        with mock.patch(ADAPTER, return_value=page):
            self.backend.run_incremental_sync()

        self.assertEqual(self._count(), 1)
        self.assertEqual(
            self.backend.cursor_since.strftime("%Y-%m-%d %H:%M:%S"),
            "2026-09-10 08:04:11",
        )
        self.assertTrue(self.backend.last_run)
        self.assertFalse(self.backend.last_error)

    def test_pages_are_followed_while_has_more(self):
        first = {
            "calls": [call_payload(id="cl_a")],
            "next_since": "2026-09-10T08:04:11Z",
            "has_more": True,
        }
        second = {
            "calls": [call_payload(id="cl_b")],
            "next_since": "2026-09-10T08:09:00Z",
            "has_more": False,
        }
        with mock.patch(ADAPTER, side_effect=[first, second]):
            self.backend.run_incremental_sync()

        self.assertEqual(self._count(), 2)

    def test_a_transport_failure_is_recorded_and_the_cursor_holds(self):
        from ..components.adapter import VoxbiTransportError

        with mock.patch(ADAPTER, side_effect=VoxbiTransportError("boom")):
            self.backend.run_incremental_sync()

        self.assertEqual(self._count(), 0)
        self.assertFalse(self.backend.cursor_since)
        self.assertIn("boom", self.backend.last_error)
