# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..components.batch_importer import VoxbiBatchImporter

# Plain http is tolerated only against these, for local development.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "host.docker.internal")
LOCAL_SUFFIXES = (".test", ".localhost")

_logger = logging.getLogger(__name__)


class VoxbiBackend(models.Model):
    """Per-tenant configuration for one Voxbi connection."""

    _name = "voxbi.backend"
    _description = "Voxbi Backend"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    cockpit_url = fields.Char(
        required=True,
        help="Base URL of Voxbi Cockpit, for example https://cockpit.voxbi.com",
    )
    api_key = fields.Char(
        required=True,
        help="Cockpit API key. It authenticates this Odoo to Voxbi. It grants "
        "Voxbi no access to this database.",
    )

    # Incremental sync walks forward from this point.
    cursor_since = fields.Datetime(readonly=True)
    # Backfill walks backward from this point until backfill_done.
    cursor_before = fields.Datetime(readonly=True)
    backfill_done = fields.Boolean(default=False, readonly=True)

    last_run = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    @api.constrains("cockpit_url")
    def _check_cockpit_url(self):
        """Require https, except against a local host.

        A tenant sending its Cockpit API key over plaintext is exactly what
        this design exists to avoid, so https is the rule. Local development
        runs Cockpit on a docker host address that has no certificate, so
        plain http is allowed there and nowhere else.
        """
        for backend in self:
            url = (backend.cockpit_url or "").strip()
            if url.startswith("https://"):
                continue
            if url.startswith("http://"):
                host = urlsplit(url).hostname or ""
                if host in LOCAL_HOSTS or host.endswith(LOCAL_SUFFIXES):
                    continue
                raise ValidationError(
                    self.env._(
                        "Plain http is only allowed for a local Cockpit. "
                        "Use https:// for %(host)s.", host=host
                    )
                )
            raise ValidationError(
                self.env._("The Cockpit URL must start with https://")
            )

    def run_incremental_sync(self):
        """Pull everything changed since the cursor. Errors are recorded, not raised.

        A cron must not die on one unreachable tenant, so the failure is
        written to last_error and the next tick retries from the same cursor.
        """
        for backend in self:
            try:
                VoxbiBatchImporter(backend.env, backend).run_incremental()
            except Exception as exc:  # noqa: BLE001 - recorded, see docstring
                backend.sudo().write({"last_error": str(exc)})
                _logger.exception(
                    "Voxbi incremental sync failed for backend %s", backend.id
                )
            else:
                backend.sudo().write(
                    {"last_run": fields.Datetime.now(), "last_error": False}
                )

    @api.model
    def _cron_incremental_sync(self):
        self.search([("active", "=", True)]).run_incremental_sync()
