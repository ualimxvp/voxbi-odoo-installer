# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import VoxbiConnectorCase


@tagged("post_install", "-at_install")
class TestBackend(VoxbiConnectorCase):
    def test_backend_is_created_with_defaults(self):
        self.assertTrue(self.backend.active)
        self.assertFalse(self.backend.backfill_done)
        self.assertFalse(self.backend.cursor_since)

    def test_cockpit_url_must_be_https(self):
        with self.assertRaises(ValidationError):
            self.env["voxbi.backend"].create(
                {
                    "name": "Insecure",
                    "cockpit_url": "http://cockpit.voxbi.com",
                    "api_key": "k",
                }
            )

    def _make(self, url):
        return self.env["voxbi.backend"].create(
            {"name": "URL check", "cockpit_url": url, "api_key": "k"}
        )

    def test_http_is_allowed_for_local_hosts(self):
        for url in [
            "http://localhost:8083",
            "http://127.0.0.1:8083",
            "http://host.docker.internal:8083",
            "http://cockpit.test",
        ]:
            self.assertTrue(self._make(url), f"should accept {url}")

    def test_http_is_rejected_for_a_remote_host(self):
        with self.assertRaises(ValidationError):
            self._make("http://cockpit.voxbi.com")

    def test_a_non_http_scheme_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._make("ftp://cockpit.test")

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertTrue(self._make("  https://cockpit.voxbi.com  "))
