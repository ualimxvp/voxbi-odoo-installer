# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging

import requests

_logger = logging.getLogger(__name__)

# A hung request inside a job holds a worker, so fail fast and let the
# job retry policy decide when to try again.
REQUEST_TIMEOUT = 20

CALLS_PATH = "/api/v1/odoo-connector/calls"


class VoxbiTransportError(Exception):
    """Cockpit was unreachable, or answered with a non-200 status."""


class VoxbiAdapter:
    """Outbound HTTP client for one Voxbi backend."""

    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend

    def fetch_since(self, since, limit):
        """Calls changed at or after `since`, oldest first."""
        return self._get({"since": since, "limit": limit})

    def fetch_before(self, before, limit):
        """Calls started before `before`, newest first."""
        return self._get({"before": before, "limit": limit})

    def _get(self, params):
        backend = self.backend_record
        url = backend.cockpit_url.rstrip("/") + CALLS_PATH
        headers = {
            "Authorization": f"Bearer {backend.api_key}",
            "Accept": "application/json",
        }
        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise VoxbiTransportError(f"Cockpit unreachable: {exc}") from exc

        if response.status_code != 200:
            raise VoxbiTransportError(
                f"Cockpit returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()
