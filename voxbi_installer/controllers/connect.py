# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

"""Cockpit connect callback: the module's one inbound HTTP endpoint.

This module was designed to expose no inbound HTTP endpoint at all: Cockpit
is only ever called by Odoo, never the other way round. This callback is a
deliberate, narrow exception to that, made because:

* it is reached only by the customer's own browser, sent here by Cockpit's
  consent screen after the customer logs into Cockpit itself. Voxbi never
  initiates a connection into the customer's Odoo;
* the browser hands it a single-use, ten-minute authorization code, not a
  credential;
* the actual credential (the Cockpit API key) never passes through the
  browser or this route's query string at all. It arrives only via the
  server-to-server POST this controller makes to Cockpit's token endpoint,
  and is written straight onto the voxbi.backend record.
"""

import logging

import requests
from markupsafe import escape

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

TOKEN_PATH = "/api/v1/odoo-connect/token"
REQUEST_TIMEOUT = 20


class ConnectError(Exception):
    """A user-facing failure of the connect flow. The message is safe to render."""


class VoxbiConnectController(http.Controller):

    @http.route(
        "/voxbi/connect/callback",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def voxbi_connect_callback(self, state=None, code=None, **kwargs):
        try:
            self._complete_connect(request.env, state, code)
        except ConnectError as exc:
            return self._render_error(str(exc))

        action = request.env.ref("voxbi_installer.action_voxbi_backend")
        return request.redirect(f"/odoo/action-{action.id}")

    @classmethod
    def _complete_connect(cls, env, state, code):
        """Validate the callback and write the exchanged credentials onto voxbi.backend.

        Raises ConnectError (safe to show the user) on any failure. The
        outbound call to Cockpit is only ever made once the group check,
        state check and code presence have all passed.
        """
        if not env.user.has_group("base.group_system"):
            raise ConnectError(env._(
                "You are not allowed to configure the Voxbi connection."
            ))

        Setup = env["voxbi.installer.setup"]
        if not Setup._consume_connect_state(state):
            raise ConnectError(env._(
                "This connection link is invalid or has expired. Start again "
                "from the Voxbi Configuration page."
            ))

        if not code:
            raise ConnectError(env._(
                "Voxbi Cockpit did not send an authorization code."
            ))

        base_url = Setup._cockpit_base_url()
        try:
            # Cockpit binds the code to the redirect_uri it was issued for and
            # validates it as required, so it has to be sent back verbatim.
            response = requests.post(
                f"{base_url}{TOKEN_PATH}",
                json={"code": code, "redirect_uri": Setup._connect_redirect_uri()},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            _logger.exception("Voxbi connect: token exchange request failed")
            raise ConnectError(env._(
                "Could not reach Voxbi Cockpit to finish connecting. Please try again."
            )) from None

        if response.status_code != 200:
            _logger.warning(
                "Voxbi connect: token exchange rejected (HTTP %s)",
                response.status_code,
            )
            raise ConnectError(env._(
                "Voxbi Cockpit rejected the connection request. Please try again."
            ))

        try:
            body = response.json()
        except ValueError:
            _logger.warning("Voxbi connect: token endpoint returned a non-JSON body")
            raise ConnectError(env._(
                "Voxbi Cockpit returned an unexpected response. Please try again."
            )) from None

        api_key = body.get("api_key")
        # Cockpit names this cockpit_base_url in its token response.
        cockpit_url = body.get("cockpit_base_url")
        pbx_id = body.get("pbx_id")
        if not api_key or not cockpit_url:
            _logger.warning(
                "Voxbi connect: token endpoint response was missing expected fields"
            )
            raise ConnectError(env._(
                "Voxbi Cockpit did not return the expected connection details."
            ))

        try:
            env["voxbi.backend"].sudo()._connect_upsert(
                cockpit_url=cockpit_url, api_key=api_key, pbx_id=pbx_id
            )
        except ValidationError as exc:
            raise ConnectError(str(exc)) from exc

    @staticmethod
    def _render_error(message):
        html = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            "<title>Voxbi Connect</title></head>"
            "<body style=\"font-family:sans-serif;max-width:40rem;margin:3rem auto\">"
            "<h1>Could not connect to Voxbi Cockpit</h1>"
            f"<p>{escape(message)}</p>"
            "</body></html>"
        )
        return request.make_response(html, headers=[("Content-Type", "text/html")])
