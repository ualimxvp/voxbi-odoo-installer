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
            return existing
        return self.env["x_voxbi.calls"].create(values)
