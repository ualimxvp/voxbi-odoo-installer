# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import logging

from .adapter import VoxbiAdapter
from .importer import VoxbiCallImporter

_logger = logging.getLogger(__name__)

PAGE_SIZE = 200
# A cron tick must finish well inside the minute, so cap how far one run will
# chase pages. Anything left is picked up on the next tick.
MAX_PAGES_PER_RUN = 10
# Where an empty cursor starts from. Backfill covers everything older.
INITIAL_SINCE = "1970-01-01T00:00:00Z"


class VoxbiBatchImporter:
    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend
        self.adapter = VoxbiAdapter(env, backend)
        self.importer = VoxbiCallImporter(env, backend)

    def run_incremental(self):
        backend = self.backend_record
        adapter = self.adapter
        importer = self.importer

        since = INITIAL_SINCE
        if backend.cursor_since:
            since = backend.cursor_since.strftime("%Y-%m-%dT%H:%M:%SZ")

        for _page in range(MAX_PAGES_PER_RUN):
            response = adapter.fetch_since(since, PAGE_SIZE)
            for payload in response.get("calls") or []:
                importer.run(payload)

            next_since = response.get("next_since")
            if next_since:
                since = next_since
                backend.sudo().write(
                    {"cursor_since": next_since.replace("T", " ").replace("Z", "")[:19]}
                )
            if not response.get("has_more"):
                break
