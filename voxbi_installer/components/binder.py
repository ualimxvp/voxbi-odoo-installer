# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).


class VoxbiBinder:
    """Maps a Voxbi call id to a local voxbi.call record.

    The binding lives on the record itself rather than in a separate binding
    model: a call exists in Odoo only because we synced it, so there is no
    second record to bind to.
    """

    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend

    def to_internal(self, external_id, unwrap=False):
        return self.env["voxbi.call"].search(
            [
                ("backend_id", "=", self.backend_record.id),
                ("external_id", "=", external_id),
            ],
            limit=1,
        )
