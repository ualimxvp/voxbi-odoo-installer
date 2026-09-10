# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import fields, models


class VoxbiCall(models.Model):
    _name = "voxbi.call"
    _description = "Voxbi Call"
    _order = "started_at desc"
    _rec_name = "phone"

    backend_id = fields.Many2one(
        "voxbi.backend", required=True, ondelete="cascade", index=True
    )
    # The Voxbi call id. Stable for the life of the call, including after AI
    # enrichment, which is what lets the importer be idempotent.
    external_id = fields.Char(required=True, index=True, readonly=True)

    started_at = fields.Datetime(readonly=True)
    ended_at = fields.Datetime(readonly=True)
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")], readonly=True
    )
    duration = fields.Integer(readonly=True, help="Total seconds")
    billsec = fields.Integer(readonly=True, help="Billable seconds")
    phone = fields.Char(readonly=True)
    contact_name = fields.Char(readonly=True)
    contact_email = fields.Char(readonly=True)
    recording_url = fields.Char(readonly=True)

    transcription = fields.Text(readonly=True)
    summary = fields.Text(readonly=True)
    translation = fields.Text(readonly=True)
    keywords = fields.Char(readonly=True)
    ai_categories = fields.Char(readonly=True)

    partner_id = fields.Many2one("res.partner", index=True, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Odoo user",
        index=True,
        readonly=True,
        help="The internal user this call belongs to.",
    )
    participant_ids = fields.One2many("voxbi.call.participant", "call_id")

    _sql_constraints = [
        (
            "external_id_uniq",
            "unique(backend_id, external_id)",
            "A call with this Voxbi id already exists for this backend.",
        )
    ]
