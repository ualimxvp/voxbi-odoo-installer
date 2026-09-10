# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from unittest import mock

from odoo.tests.common import tagged

from ..components.adapter import VoxbiAdapter, VoxbiTransportError
from .common import VoxbiConnectorCase

PATCH = "odoo.addons.voxbi_installer.components.adapter.requests.get"


@tagged("post_install", "-at_install")
class TestAdapter(VoxbiConnectorCase):
    def _adapter(self):
        return VoxbiAdapter(self.env, self.backend)

    def test_fetch_since_builds_url_and_auth(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"calls": [], "has_more": False}
        with mock.patch(PATCH, return_value=response) as get:
            result = self._adapter().fetch_since("2026-09-10T08:00:00Z", 200)

        self.assertEqual(result, {"calls": [], "has_more": False})
        url = get.call_args.args[0]
        self.assertEqual(
            url, "https://cockpit.test/api/v1/odoo-connector/calls"
        )
        self.assertEqual(
            get.call_args.kwargs["params"],
            {"since": "2026-09-10T08:00:00Z", "limit": 200},
        )
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"], "Bearer test-key"
        )

    def test_fetch_before_uses_before_param(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"calls": [], "has_more": False}
        with mock.patch(PATCH, return_value=response) as get:
            self._adapter().fetch_before("2026-09-10T08:00:00Z", 50)

        self.assertEqual(
            get.call_args.kwargs["params"],
            {"before": "2026-09-10T08:00:00Z", "limit": 50},
        )

    def test_non_200_raises_transport_error(self):
        response = mock.Mock(status_code=503, text="upstream down")
        with mock.patch(PATCH, return_value=response):
            with self.assertRaises(VoxbiTransportError):
                self._adapter().fetch_since("2026-09-10T08:00:00Z", 200)
