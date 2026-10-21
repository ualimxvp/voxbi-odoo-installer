# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests.common import TransactionCase

# The x_voxbi.* models are not part of this module. Voxbi Cockpit installs them
# over XML-RPC into the customer's database, so a fresh test database does not
# have them and every test that imports a call fails with KeyError. Create the
# subset the connector reads and writes.
#
# These are plain stored fields. On the installed model x_partner_id is a stored
# compute over x_remote_person_number/x_remote_person_email, but nothing under
# test asserts on it (see the comment in test_matcher), so the fixture leaves the
# compute out rather than maintaining a second copy of it that could drift.
# x_name is not listed: Odoo creates it itself as the rec_name of a manual
# model, and declaring it again violates ir_model_fields_name_unique.
CALL_CHAR_FIELDS = [
    "x_phone",
    "x_email",
    "x_call_type",
    "x_duration",
    "x_billsec",
    "x_remote_person",
    "x_remote_person_number",
    "x_remote_person_email",
    "x_call_recording",
    "x_start_time",
    "x_answer_time",
    "x_end_time",
]
CALL_TEXT_FIELDS = [
    "x_transcription",
    "x_summary",
    "x_translation",
    "x_keywords",
    "x_ai_categories",
]
PARTICIPANT_CHAR_FIELDS = ["x_number", "x_email", "x_type"]


def ensure_installed_models(env):
    """Create the Cockpit-installed models if this database has none.

    A database that Cockpit has really provisioned keeps its own definitions:
    the real ones are richer than this, and overwriting them would test the
    fixture instead of the integration.
    """
    # Ask the database, not the registry. A manual model created by an earlier
    # test stays in the registry after that test's transaction rolls back, so a
    # registry check reports a model whose ir_model rows and table are both gone.
    if env["ir.model"].sudo().search_count([("model", "=", "x_voxbi.calls")]):
        return

    IrModel = env["ir.model"].sudo()
    IrModel.create([
        {"name": "Voxbi Calls", "model": "x_voxbi.calls", "state": "manual"},
        {
            "name": "Voxbi Call Participants",
            "model": "x_voxbi.call_participants",
            "state": "manual",
        },
    ])

    def spec(model, name, ttype, **extra):
        return dict(
            {
                "model": model,
                "model_id": env["ir.model"]._get_id(model),
                "name": name,
                "field_description": name[2:].replace("_", " ").title(),
                "ttype": ttype,
                "state": "manual",
            },
            **extra,
        )

    calls, parts = "x_voxbi.calls", "x_voxbi.call_participants"
    values = [spec(calls, "x_internal_id", "integer")]
    values += [spec(calls, f, "char") for f in CALL_CHAR_FIELDS]
    values += [spec(calls, f, "text") for f in CALL_TEXT_FIELDS]
    values += [
        spec(calls, "x_user_id", "many2one", relation="res.users"),
        spec(calls, "x_partner_id", "many2one", relation="res.partner"),
        spec(parts, "x_call_id", "many2one", relation=calls),
        spec(parts, "x_user_id", "many2one", relation="res.users"),
    ]
    values += [spec(parts, f, "char") for f in PARTICIPANT_CHAR_FIELDS]
    env["ir.model.fields"].sudo().create(values)

    # The one2many needs its inverse to exist first.
    env["ir.model.fields"].sudo().create([
        spec(
            calls,
            "x_participants",
            "one2many",
            relation=parts,
            relation_field="x_call_id",
        )
    ])



class VoxbiConnectorCase(TransactionCase):
    """Shared fixture: one backend pointing at a fake Cockpit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_installed_models(cls.env)
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
