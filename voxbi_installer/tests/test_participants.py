# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests import TransactionCase

from .common import ensure_installed_models


class TestParticipants(TransactionCase):
    def setUp(self):
        super().setUp()
        ensure_installed_models(self.env)
        self.backend = self.env["voxbi.backend"].create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.example.com",
            "api_key": "k",
        })
        from odoo.addons.voxbi_installer.components.importer import VoxbiCallImporter

        self.importer = VoxbiCallImporter(self.env, self.backend)

    def payload(self, participants):
        return {
            "id": 1,
            "cdrs_id": 59726,
            "started_at": "2026-09-15T08:01:02Z",
            "answered_at": "2026-09-15T08:01:20Z",
            "ended_at": "2026-09-15T08:03:40Z",
            "started_at_display": "15 Sep 08:01",
            "answered_at_display": "15 Sep 08:01",
            "ended_at_display": "15 Sep 08:03",
            "direction": "INCOMING",
            "duration": "2m 38s",
            "billsec": "2m 20s",
            "phone": "+352661123456",
            "contact_name": "Anne Weber",
            "contact_email": "anne@example.lu",
            "recording_url": False,
            "transcription": False,
            "summary": False,
            "translation": False,
            "keywords": False,
            "ai_categories": False,
            "participants": participants,
        }

    def test_writes_participants_linked_to_the_call(self):
        call = self.importer.run(self.payload([
            {"id": "p1", "name": "Anne Weber", "type": "caller", "number": "+352661123456"},
        ]))

        rows = self.env["x_voxbi.call_participants"].search([("x_call_id", "=", call.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.x_name, "Anne Weber")
        # The payload key is "number". Reading "phone" lost every number.
        self.assertEqual(rows.x_number, "+352661123456")
        # The push path writes capitalised Caller/Callee; the importer now
        # normalises the feed's lowercase "caller"/"callee" to match.
        self.assertEqual(rows.x_type, "Caller")

    def test_reimporting_replaces_rather_than_accumulates(self):
        first = self.importer.run(self.payload([
            {"id": "p1", "name": "Anne", "type": "caller", "number": "+352661123456"},
        ]))
        self.importer.run(self.payload([
            {"id": "p2", "name": "Bob", "type": "callee", "number": "+352661999999"},
        ]))

        rows = self.env["x_voxbi.call_participants"].search([("x_call_id", "=", first.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.x_name, "Bob")

    def test_a_call_with_no_participants_is_fine(self):
        call = self.importer.run(self.payload([]))
        self.assertTrue(call)
        self.assertFalse(
            self.env["x_voxbi.call_participants"].search([("x_call_id", "=", call.id)])
        )
