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
        existing = self.binder.to_internal(payload["id"])

        if payload.get("deleted"):
            if existing:
                existing.unlink()
            return self.env["voxbi.call"].browse()

        values = self.mapper.values(payload)

        partner = self.matcher.find_partner(
            payload.get("phone"), payload.get("contact_email")
        )
        values["partner_id"] = partner.id or False

        if existing:
            existing.write(values)
            return existing
        return self.env["voxbi.call"].create(values)
