# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests.common import TransactionCase


class VoxbiConnectorCase(TransactionCase):
    """Shared fixture: one backend pointing at a fake Cockpit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env["voxbi.backend"].create(
            {
                "name": "Test backend",
                "cockpit_url": "https://cockpit.test",
                "api_key": "test-key",
            }
        )


def call_payload(**overrides):
    """A feed record matching the contract, overridable per test."""
    payload = {
        "id": "cl_01J8XQ",
        "cdrs_id": 50001,
        "updated_at": "2026-09-10T08:04:11Z",
        "started_at": "2026-09-10T08:01:02Z",
        "ended_at": "2026-09-10T08:03:40Z",
        "direction": "inbound",
        "duration": 158,
        "billsec": 142,
        "phone": "+352661123456",
        "contact_name": "Anne Weber",
        "contact_email": "anne@example.lu",
        "recording_url": "https://cockpit.test/rec/cl_01J8XQ",
        "transcription": "hello",
        "summary": "a summary",
        "translation": "",
        "keywords": "invoice",
        "ai_categories": "support",
        "participants": [
            {
                "id": "pt_01J8XR",
                "name": "Anne Weber",
                "phone": "+352661123456",
                "email": "anne@example.lu",
                "internal": False,
            }
        ],
        "deleted": False,
    }
    payload.update(overrides)
    return payload
