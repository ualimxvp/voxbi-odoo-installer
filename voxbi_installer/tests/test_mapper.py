# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests import TransactionCase


class TestMapper(TransactionCase):
    def setUp(self):
        super().setUp()
        self.backend = self.env["voxbi.backend"].create({
            "name": "Voxbi Cockpit",
            "cockpit_url": "https://cockpit.example.com",
            "api_key": "k",
        })
        from odoo.addons.voxbi_installer.components.mapper import VoxbiCallMapper

        self.mapper = VoxbiCallMapper(self.env, self.backend)

    def payload(self, **overrides):
        base = {
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
            "recording_url": "https://cockpit.example.com/rec/1",
            "transcription": "hello",
            "summary": "a summary",
            "translation": "une traduction",
            "keywords": "invoice, renewal",
            "ai_categories": "support",
            "participants": [],
        }
        base.update(overrides)
        return base

    def test_maps_the_join_key(self):
        values = self.mapper.values(self.payload())
        self.assertEqual(values["x_internal_id"], 59726)

    def test_maps_all_three_timestamps(self):
        values = self.mapper.values(self.payload())
        self.assertEqual(values["x_start_time"], "15 Sep 08:01")
        # answered_at was silently dropped before this change.
        self.assertEqual(values["x_answer_time"], "15 Sep 08:01")
        self.assertEqual(values["x_end_time"], "15 Sep 08:03")

    def test_does_not_reformat_the_display_strings(self):
        values = self.mapper.values(self.payload())
        # The feed already rendered these to match the push path. Reformatting
        # here, from the ISO values or otherwise, is how the same call ends up
        # looking different depending on which pipeline wrote it.
        self.assertEqual(values["x_start_time"], "15 Sep 08:01")

    def test_maps_the_text_fields(self):
        values = self.mapper.values(self.payload())
        self.assertEqual(values["x_call_type"], "INCOMING")
        self.assertEqual(values["x_remote_person_number"], "+352661123456")
        self.assertEqual(values["x_remote_person"], "Anne Weber")
        self.assertEqual(values["x_remote_person_email"], "anne@example.lu")
        self.assertEqual(values["x_transcription"], "hello")
        self.assertEqual(values["x_summary"], "a summary")
        self.assertEqual(values["x_translation"], "une traduction")
        self.assertEqual(values["x_keywords"], "invoice, renewal")
        self.assertEqual(values["x_ai_categories"], "support")
        self.assertEqual(values["x_call_recording"], "https://cockpit.example.com/rec/1")

    def test_duration_and_billsec_pass_through_as_text(self):
        values = self.mapper.values(self.payload())
        self.assertEqual(values["x_duration"], "2m 38s")
        self.assertEqual(values["x_billsec"], "2m 20s")

    def test_a_missing_timestamp_becomes_false(self):
        values = self.mapper.values(self.payload(answered_at_display=""))
        self.assertFalse(values["x_answer_time"])

    def test_does_not_write_relation_fields(self):
        values = self.mapper.values(self.payload())
        for field in ("x_leads_ids", "x_tickets_ids", "x_tasks_ids", "x_contacts"):
            self.assertNotIn(field, values)
