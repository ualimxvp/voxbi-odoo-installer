# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo import fields, models


class VoxbiCallParticipant(models.Model):
    _name = "voxbi.call.participant"
    _description = "Voxbi Call Participant"

    call_id = fields.Many2one(
        "voxbi.call", required=True, ondelete="cascade", index=True
    )
    external_id = fields.Char(readonly=True)
    name = fields.Char(readonly=True)
    phone = fields.Char(readonly=True)
    email = fields.Char(readonly=True)
    internal = fields.Boolean(readonly=True)
    user_id = fields.Many2one("res.users", index=True, readonly=True)
