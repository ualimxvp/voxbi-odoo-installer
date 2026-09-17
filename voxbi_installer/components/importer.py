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

        # x_partner_id is NOT written here. It is a stored, readonly computed
        # field on the installed model, matching on x_remote_person_number and
        # falling back to x_remote_person_email, entirely inside the customer's
        # database. Writing it fights the compute; filling the two fields it
        # depends on (the mapper does) is what makes the match happen.
        values["x_user_id"] = self._odoo_user(payload.get("contact_email"))

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

        x_user_id is a many2one to res.users, resolved from the participant's
        email the way the push path does (OdooService::createParticipants).
        It is not a slot for the payload's participant id. Leaving it unset
        would hide the call: the record rule on x_voxbi.calls is
        ['|', ('x_user_id','=',user.id), ('x_participants.x_user_id','=',user.id)],
        so a call matching neither is invisible to every non-admin user.
        """
        Participant = self.env["x_voxbi.call_participants"]

        Participant.search([("x_call_id", "=", call.id)]).unlink()

        for participant in payload.get("participants") or []:
            # The push path writes 'Caller'/'Callee' capitalised from a raw
            # 'caller'/'callee'. x_type is a char, so the wrong case fails
            # nothing and just shows two spellings in one list.
            is_caller = (participant.get("type") or "").lower() == "caller"

            Participant.create({
                "x_call_id": call.id,
                "x_name": participant.get("name") or False,
                "x_number": participant.get("number") or False,
                "x_email": participant.get("email") or False,
                "x_type": "Caller" if is_caller else "Callee",
                "x_user_id": self._odoo_user(participant.get("email")),
            })

    def _odoo_user(self, email):
        """The res.users id for an email, or False.

        Mirrors OdooService::getUserByPhoneNumber, which despite its name
        searches res.users on email.
        """
        if not email:
            return False
        user = self.env["res.users"].search([("email", "=", email)], limit=1)
        return user.id or False
