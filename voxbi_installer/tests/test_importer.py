# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests.common import tagged

from ..components.importer import VoxbiCallImporter
from .common import VoxbiConnectorCase, call_payload


@tagged("post_install", "-at_install")
class TestImporter(VoxbiConnectorCase):
    def _import(self, payload):
        return VoxbiCallImporter(self.env, self.backend).run(payload)

    def _calls(self):
        return self.env["x_voxbi.calls"].search([])

    def test_first_import_creates_the_call(self):
        call = self._import(call_payload())
        self.assertEqual(call.x_internal_id, 50001)

    def test_replaying_the_same_payload_creates_no_duplicate(self):
        self._import(call_payload())
        self._import(call_payload())
        self.assertEqual(len(self._calls()), 1)

    def test_late_ai_fields_update_the_existing_call(self):
        first = self._import(call_payload(transcription="", summary=""))
        second = self._import(
            call_payload(transcription="full text", summary="the summary")
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self._calls()), 1)

    def test_participants_are_replaced_not_appended_on_update(self):
        self._import(call_payload())
        call = self._import(
            call_payload(
                participants=[
                    {
                        "id": "pt_02",
                        "name": "Marc Klein",
                        "phone": "+352661999999",
                        "email": "",
                        "internal": True,
                    }
                ]
            )
        )
        self.assertTrue(call)

    def test_a_call_without_a_cdrs_id_is_skipped(self):
        payload = call_payload()
        payload.pop("cdrs_id", None)

        result = self._import(payload)

        self.assertFalse(result)
        self.assertEqual(self.env["x_voxbi.calls"].search_count([]), 0)

    def test_reimporting_the_same_call_updates_rather_than_duplicates(self):
        payload = call_payload()

        first = self._import(payload)
        second = self._import(payload)

        self.assertEqual(first.id, second.id)
        self.assertEqual(
            self.env["x_voxbi.calls"].search_count(
                [("x_internal_id", "=", int(payload["cdrs_id"]))]
            ),
            1,
        )
