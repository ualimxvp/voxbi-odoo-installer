# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).


class VoxbiBinder:
    """Maps a Voxbi call to the x_voxbi.calls record installed by Cockpit.

    The key is x_internal_id, which holds cdrs_id. The push path writes the
    same value, so a tenant that has run both pipelines ends up with one
    record per call rather than two.
    """

    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend

    def to_internal(self, cdrs_id, unwrap=False):
        if not cdrs_id:
            return self.env["x_voxbi.calls"].browse()
        return self.env["x_voxbi.calls"].search(
            [("x_internal_id", "=", int(cdrs_id))],
            limit=1,
        )
