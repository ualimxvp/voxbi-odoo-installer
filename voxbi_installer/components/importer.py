# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging

from .binder import VoxbiBinder
from .mapper import VoxbiCallMapper
from .matcher import VoxbiPartnerMatcher

_logger = logging.getLogger(__name__)


class VoxbiCallImporter:
    """Imports one call payload, creating or updating the local record."""

    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend
        self.binder = VoxbiBinder(env, backend)
        self.mapper = VoxbiCallMapper(env, backend)
        self.matcher = VoxbiPartnerMatcher(env, backend)

    def run(self, payload):
        cdrs_id = payload.get("cdrs_id")

        # crm_messages.cdrs_id is populated by the CDRS engine after the call
        # ends, so a just-ended call has no key yet. That is normal and
        # transient: the call arrives on a later poll once the key exists.
        if not cdrs_id:
            _logger.info(
                "Voxbi: call %s has no cdrs_id yet, will import on a later poll",
                payload.get("id"),
            )
            return self.env["x_voxbi.calls"].browse()

        existing = self.binder.to_internal(cdrs_id)

        values = self.mapper.values(payload)

        partner = self.matcher.find_partner(
            payload.get("phone"), payload.get("contact_email")
        )
        values["x_partner_id"] = partner.id or False

        if existing:
            existing.write(values)
            record = existing
        else:
            record = self.env["x_voxbi.calls"].create(values)

        self._sync_participants(record, payload)
        return record

    def _sync_participants(self, call, payload):
        """Replace the call's participant rows from the payload.

        The feed sends the full set every time, so delete and recreate is both
        simpler and correct: merging would leave a stale row behind whenever
        someone drops off a call.

        Payload keys are id, name, type, number. There is no phone key and no
        internal flag, whatever an older mapper assumed.

        x_user_id is a many2one to res.users, not a slot for the payload's
        participant id (an external identifier, not an internal Odoo user).
        The feed carries no internal-user reference, so it is left unset.
        """
        Participant = self.env["x_voxbi.call_participants"]

        Participant.search([("x_call_id", "=", call.id)]).unlink()

        for participant in payload.get("participants") or []:
            Participant.create({
                "x_call_id": call.id,
                "x_name": participant.get("name") or False,
                "x_number": participant.get("number") or False,
                "x_email": participant.get("email") or False,
                "x_type": participant.get("type") or False,
            })
