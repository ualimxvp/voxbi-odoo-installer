# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import psycopg2

from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .common import VoxbiConnectorCase


@tagged("post_install", "-at_install")
class TestCallModel(VoxbiConnectorCase):
    def test_call_is_created_with_participants(self):
        call = self.env["voxbi.call"].create(
            {
                "backend_id": self.backend.id,
                "external_id": "cl_1",
                "phone": "+352661123456",
                "direction": "inbound",
                "participant_ids": [
                    (0, 0, {"external_id": "pt_1", "name": "Anne Weber"}),
                ],
            }
        )
        self.assertEqual(len(call.participant_ids), 1)
        self.assertEqual(call.participant_ids.name, "Anne Weber")

    @mute_logger("odoo.sql_db")
    def test_external_id_is_unique_per_backend(self):
        self.env["voxbi.call"].create(
            {"backend_id": self.backend.id, "external_id": "cl_dup"}
        )
        with self.assertRaises(psycopg2.IntegrityError):
            with self.env.cr.savepoint():
                self.env["voxbi.call"].create(
                    {"backend_id": self.backend.id, "external_id": "cl_dup"}
                )
