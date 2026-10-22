# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from odoo import _, api, fields, models, release
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Default Cockpit endpoint baked into the module. Override per-instance via
# the ir.config_parameter "voxbi.cockpit_url" (e.g. for staging).
DEFAULT_COCKPIT_URL = "https://cockpit.voxbi.com"
# Must be exactly "rpc" — that's the scope Odoo's _check_credentials fallback
# in res.users.apikeys looks for when authenticating XML-RPC requests.
API_KEY_SCOPE = "rpc"
API_KEY_NAME = "Voxbi installer"
# The ongoing sync authenticates as a NON-admin user with its own key, so an
# admin credential never has to outlive the install. Kept under its own name
# so rotating one never touches the other.
SYNC_API_KEY_NAME = "Voxbi sync"
# Canonical home for the choice. An ir.config_parameter is readable over
# XML-RPC and exists whether or not this module is installed, so the RPC
# installer can read it back without depending on this model.
SYNC_USER_PARAM = "voxbi.sync_user_id"
# Login for the user action_create_sync_user() provisions.
SYNC_USER_LOGIN = "voxbi.sync"
# Version of *this* installer module, sent to Cockpit purely for diagnostics.
MODULE_VERSION = "2.1.0"

# --- Cockpit connect (authorization-code) flow ----------------------------
# This sits alongside the older paste-a-key install flow above. Both talk to
# the same Cockpit, via DEFAULT_COCKPIT_URL / the "voxbi.cockpit_url"
# override. There is deliberately no second way to configure which Cockpit
# to use.
CONNECT_AUTHORIZE_PATH = "/odoo-connect/authorize"
CONNECT_CALLBACK_PATH = "/voxbi/connect/callback"
# Per-state ir.config_parameter key. Not stored in the session: the browser
# leaves and comes back on a different request once Cockpit redirects here.
CONNECT_STATE_PARAM_PREFIX = "voxbi.connect.state."
CONNECT_STATE_TTL_MINUTES = 10


class VoxbiInstallerSetup(models.Model):
    _name = "voxbi.installer.setup"
    _description = "Voxbi Setup"
    _order = "id desc"

    # Cockpit API v2 auth: a long-lived Bearer API key the admin creates in
    # Cockpit (with the "Is Odoo Installer" scope). Reusable across every call;
    # replaces the old single-use install token.
    cockpit_api_key = fields.Char(
        string="Cockpit API key",
        help="The Bearer API key created in Voxbi Cockpit (Integrations → Add "
        "integration → API key) with the “Is Odoo Installer” scope. It is reusable "
        "and long-lived; the module sends it as a Bearer token on every request to "
        "Cockpit. Treat it like a password.",
    )
    sync_user_id = fields.Many2one(
        "res.users",
        string="Sync user",
        domain="[('id', 'in', allowed_sync_user_ids)]",
        help="The Odoo user Voxbi authenticates as for the ongoing call sync. "
        "Deliberately not an administrator: this credential is long-lived, "
        "unlike the install credential, which is discarded once setup succeeds.",
    )
    sync_user_swapped = fields.Boolean(
        readonly=True,
        help="True once the sync user's credentials have been handed to Cockpit. "
        "Guards against re-minting a key on every status poll.",
    )
    allowed_sync_user_ids = fields.Many2many(
        "res.users",
        compute="_compute_allowed_sync_user_ids",
        help="Internal, non-administrator users. Drives the sync user domain.",
    )
    has_sync_user_candidates = fields.Boolean(
        compute="_compute_allowed_sync_user_ids",
        help="False on a fresh Odoo whose only user is the administrator.",
    )
    is_connected = fields.Boolean(
        compute="_compute_connection_state",
        help="True once consent has produced a Cockpit credential. Drives which "
        "half of the configuration page is shown.",
    )
    connected_cockpit_url = fields.Char(compute="_compute_connection_state")
    connected_pbx_id = fields.Char(compute="_compute_connection_state")
    connected_sync_user = fields.Char(compute="_compute_connection_state")
    consent = fields.Boolean(
        string="I authorize Voxbi to configure this Odoo",
        default=False,
        help="Required. By ticking this you authorize the module to generate an "
        "Odoo API key for your user and send it, together with this instance's "
        "connection details, to Voxbi Cockpit over HTTPS so it can configure "
        "the Voxbi integration. You can revoke the key at any time.",
    )
    sync_sip_configurations = fields.Boolean(
        string="Sync SIP configurations to Odoo VoIP",
        help="If on, Voxbi pushes SIP settings into Odoo's VoIP module after install.",
        default=False,
    )
    is_active = fields.Boolean(
        string="Is active",
        help="If active, sync will be active for this integration.",
        default=True,
    )
    state = fields.Selection(
        [
            ("draft", "Ready to install"),
            ("installing", "Installing…"),
            ("done", "Installed"),
            ("failed", "Failed"),
        ],
        default="draft",
        readonly=True,
    )
    # Set once register-install succeeds. Also the sentinel for "have we
    # registered with Cockpit yet?" — the v2 status/get/update endpoints derive
    # the PBX from the API key, so there is no token id to carry around.
    integration_id = fields.Char(readonly=True)
    message = fields.Text(readonly=True)
    # Content is built server-side from Cockpit's log array with every message
    # HTML-escaped (see _render_output_html). We still keep Odoo's sanitizer on
    # as defense in depth, allowing the inline styles the log console relies on.
    output_html = fields.Html(
        string="Output",
        readonly=True,
        sanitize=True,
        sanitize_attributes=True,
        sanitize_style=True,
    )

    @api.depends_context("uid")
    def _compute_allowed_sync_user_ids(self):
        """Internal users that are not administrators.

        Excluded by GROUP rather than by login: "admin" is a login, not a
        privilege level, and a customer may well have several system users.
        Portal/public accounts (share=True) cannot hold an rpc key at all.
        """
        admin_ids = set(self.env.ref("base.group_system").sudo().users.ids)
        candidates = self.env["res.users"].sudo().search([
            ("share", "=", False),
            ("active", "=", True),
        ])
        allowed = candidates.filtered(lambda u: u.id not in admin_ids)
        for record in self:
            record.allowed_sync_user_ids = allowed
            record.has_sync_user_candidates = bool(allowed)

    @api.depends_context("uid")
    def _compute_connection_state(self):
        """Read the connection off the backend record.

        Holding an api_key IS being connected: it is the credential every
        outbound call uses, so anything else would be a second opinion that can
        disagree with reality.
        """
        backend = self.env["voxbi.backend"].sudo().search([], limit=1, order="id asc")
        for record in self:
            record.is_connected = bool(backend and backend.api_key)
            record.connected_cockpit_url = backend.cockpit_url if backend else False
            record.connected_pbx_id = self.env["ir.config_parameter"].sudo().get_param(
                "voxbi.pbx_id", default=False
            )
            record.connected_sync_user = (
                record.sync_user_id.login if record.sync_user_id else False
            )

    def action_create_sync_user(self):
        """Create a dedicated, non-admin user for the sync to authenticate as.

        A brand new Odoo has only the administrator, so the dropdown would be
        empty and the flow would dead-end on exactly the instance where this
        matters most. A plain internal user is enough here: the Voxbi groups it
        needs are granted later by the RPC installer, which is the only side
        that knows what those groups are.
        """
        self.ensure_one()
        existing = self.env["res.users"].sudo().search(
            [("login", "=", SYNC_USER_LOGIN)], limit=1
        )
        if existing:
            if not existing.active:
                existing.active = True
            self.sync_user_id = existing
            return

        self.sync_user_id = self.env["res.users"].sudo().create({
            "name": "Voxbi Sync",
            "login": SYNC_USER_LOGIN,
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    @api.depends("state")
    def _compute_display_name(self):
        # Without a name/_rec_name the breadcrumb falls back to "model,id"
        # (e.g. "voxbi.installer.setup,1"). Give it a stable human label.
        for record in self:
            record.display_name = _("Voxbi Setup")

    # --- helpers ---------------------------------------------------------

    def _cockpit_base_url(self):
        url = self.env["ir.config_parameter"].sudo().get_param(
            "voxbi.cockpit_url", DEFAULT_COCKPIT_URL
        )
        return self._require_https_cockpit_url(
            url, _('system parameter "voxbi.cockpit_url"')
        )

    def _require_https_cockpit_url(self, url, source):
        """Reject anything but a plain https:// URL.

        Shared by every place this module picks a Cockpit host to talk to,
        whichever record the URL came from (the system parameter or a
        voxbi.backend row): the Cockpit Bearer key and a freshly minted Odoo
        service key are sent to this host, so this blocks file://, http://
        and SSRF to internal/metadata endpoints even if the source value is
        tampered with.
        """
        url = (url or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise UserError(_(
                "The Voxbi Cockpit URL (%(source)s) must be a valid https:// "
                "URL. Current value: %(url)s"
            ) % {"source": source, "url": url or _("empty")})
        return url

    def _odoo_self_url(self):
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    def _odoo_version(self):
        # e.g. "18.0", "17.0" (or "saas~17.4" on Odoo Online). Stays within
        # Cockpit's 16-char odoo_version limit and is always the real version.
        return release.major_version

    def _cockpit_api_key(self):
        """The Cockpit Bearer key, whichever way the customer obtained it.

        Two flows produce it and they write to different places: pasting a key
        fills cockpit_api_key on this wizard, while the connect flow writes the
        exchanged key onto voxbi.backend (ConnectController._complete_connect)
        and never touches this field. Reading only the field meant every
        outbound call sent no Authorization header at all for a connect-flow
        customer, and Cockpit answered 401 "missing, invalid, or expired",
        pointing them at a key they were right not to have.

        A live connection wins over the field. The connect flow's key was
        issued by Cockpit and is the one it will recognise, while the field
        can still be holding whatever was typed during an earlier failed
        attempt, which is exactly the state a customer reaches this screen in.
        The field is the fallback for an install that never connected.

        Both flows target the host in "voxbi.cockpit_url" -- the connect token
        exchange reads it too -- so there is no credential/host mismatch here.
        """
        backend = self.env["voxbi.backend"].sudo().search([], limit=1, order="id asc")
        connected = (backend.api_key or "").strip() if backend else ""

        return connected or (self.cockpit_api_key or "").strip()

    def _auth_headers(self):
        """Bearer + Accept headers required on every Cockpit request (API v2)."""
        headers = {"Accept": "application/json"}
        key = self._cockpit_api_key()
        if key:
            headers["Authorization"] = "Bearer %s" % key
        return headers

    def _issue_api_key_for_current_user(self):
        """Generate a fresh Odoo API key for the logged-in user.

        The customer is never asked for credentials — the wizard runs as a
        logged-in admin, so we mint an API key on their behalf via
        `res.users.apikeys` and hand the plaintext (returned once) to Voxbi
        Cockpit, which uses it as the XML-RPC password. This is the Odoo-side
        `service_key`, distinct from the Cockpit Bearer API key.
        """
        user = self.env.user
        # Revoke only *our own* prior installer key (matched by name) so
        # rotation is clean — never touch other "rpc"-scope keys the user may
        # rely on for unrelated XML-RPC integrations.
        ApiKeys = self.env["res.users.apikeys"].sudo()
        prior = ApiKeys.search([
            ("user_id", "=", user.id),
            ("scope", "=", API_KEY_SCOPE),
            ("name", "=", API_KEY_NAME),
        ])
        if prior:
            prior.unlink()

        plaintext = self._generate_api_key(API_KEY_SCOPE, API_KEY_NAME)
        return user.login, plaintext

    def _issue_api_key_for_sync_user(self):
        """Mint a persistent Odoo API key that BELONGS to the chosen sync user.

        `res.users.apikeys._generate` writes `self.env.user.id` and takes no
        user argument, so the only way to mint for someone else is to change
        env.user: `with_user(target)`. sudo() is then required and keeps that
        uid (it sets su=True rather than switching to superuser), which is what
        lets a non-admin hold a key with no expiry -- without it Odoo refuses,
        since a plain internal user's group caps the duration.

        Verified against Odoo 18 and 19.

        Returns (login, plaintext) or (None, None) when no sync user is set.
        """
        self.ensure_one()
        user = self.sync_user_id
        if not user:
            return None, None

        ApiKeys = self.env["res.users.apikeys"].sudo()
        # Replace only OUR key for this user, matched by name, so re-running
        # setup rotates rather than accumulates and other rpc keys are safe.
        prior = ApiKeys.search([
            ("user_id", "=", user.id),
            ("scope", "=", API_KEY_SCOPE),
            ("name", "=", SYNC_API_KEY_NAME),
        ])
        if prior:
            prior.unlink()

        keys_as_user = self.env["res.users.apikeys"].with_user(user).sudo()
        try:
            plaintext = keys_as_user._generate(API_KEY_SCOPE, SYNC_API_KEY_NAME, False)
        except TypeError:
            plaintext = keys_as_user._generate(API_KEY_SCOPE, SYNC_API_KEY_NAME)

        # Recorded where the RPC installer can read it back without this model.
        self.env["ir.config_parameter"].sudo().set_param(
            SYNC_USER_PARAM, str(user.id)
        )

        return user.login, plaintext

    def _swap_to_sync_user(self):
        """Hand Cockpit the sync user's credentials, after a successful install.

        Deliberately after, not during: a failed install must never put the
        long-lived credential in flight. Cockpit keeps the integration at
        success and does not reset it to pending, so this cannot re-trigger the
        installer cron.
        """
        self.ensure_one()
        if not self.sync_user_id or self.sync_user_swapped:
            return

        login, api_key = self._issue_api_key_for_sync_user()
        if not login:
            return

        url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/swap-to-sync-user"
        status, body = self._post_json(url, {
            "sync_user": login,
            "sync_key": api_key,
            "sync_uid": int(self.sync_user_id.id),
        })

        if status == 200:
            self.sync_user_swapped = True
            return

        _logger.warning(
            "Voxbi: sync user swap refused (HTTP %s): %s", status, body
        )

    def _revoke_installer_key(self):
        """Delete the admin key minted for this install.

        It exists to let the RPC installer create models, views and groups,
        which the sync user has no rights to do. The moment the install
        reaches a terminal state that power is no longer needed, so the key
        goes -- on failure as much as on success, since a failed install used
        to leave a live admin rpc key behind in the customer's database with
        nothing scheduled to clean it up.

        Matched by name and scope, never scope alone: customers keep their own
        rpc keys for unrelated integrations.
        """
        self.env["res.users.apikeys"].sudo().search([
            ("scope", "=", API_KEY_SCOPE),
            ("name", "=", API_KEY_NAME),
        ]).unlink()

    def _generate_api_key(self, scope, name):
        """Call res.users.apikeys._generate with whichever signature this Odoo build exposes.

        Odoo 17+ requires `expiration_date` (third arg). Falsy = persistent key,
        which is what we want here (the installer needs ongoing access). Sudo
        lets us mint a persistent key even when the user's group caps the max
        duration. The fallback covers builds with the older 2-arg signature.
        """
        ApiKeys = self.env["res.users.apikeys"].sudo()
        try:
            return ApiKeys._generate(scope, name, False)
        except TypeError:
            # Older builds without the expiration_date arg.
            return ApiKeys._generate(scope, name)

    def _post_json(self, url, payload, timeout=15):
        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return resp.getcode(), json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") or "{}"
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, {"raw": body}
        except urllib.error.URLError as e:
            return 0, {"error": "network", "reason": str(e)}

    def _post_json_with_key(self, url, payload, key, timeout=15):
        """POST JSON to Cockpit authenticated with an explicit bearer key.

        Used only by action_disconnect: that call must authenticate with
        whichever credential the customer actually holds (the connect flow's
        backend key, or the older pasted install key), not with whatever
        _auth_headers()/cockpit_api_key happens to hold, which is empty for a
        connect-flow customer.
        """
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer %s" % key
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return resp.getcode(), json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") or "{}"
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, {"raw": body}
        except urllib.error.URLError as e:
            return 0, {"error": "network", "reason": str(e)}

    def _get_json(self, url, timeout=10):
        req = urllib.request.Request(url, headers=self._auth_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return resp.getcode(), json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") or "{}"
            try:
                return e.code, json.loads(body)
            except json.JSONDecodeError:
                return e.code, {"raw": body}
        except urllib.error.URLError as e:
            return 0, {"error": "network", "reason": str(e)}

    def _api_error_message(self, status, body):
        """Map a Cockpit API v2 error response to an actionable message."""
        detail = body.get("message") or body.get("error")
        if status == 0:
            return _("Could not reach Voxbi Cockpit: %s") % (
                body.get("reason") or _("network error")
            )
        if status == 401:
            return _(
                "Voxbi Cockpit did not accept this connection. It may have been "
                "revoked or expired. Click Connect to Voxbi Cockpit to authorize "
                "again."
            )
        if status == 403:
            return _(
                "This Cockpit API key is not allowed to run the installer. In Voxbi "
                "Cockpit, make sure the key has the “Is Odoo Installer” scope and "
                "belongs to this PBX, then try again."
            )
        if status == 422:
            errors = body.get("errors") or {}
            if errors:
                fields_detail = "; ".join(
                    "%s: %s" % (
                        field,
                        ", ".join(msgs) if isinstance(msgs, (list, tuple)) else msgs,
                    )
                    for field, msgs in errors.items()
                )
                return _("Voxbi Cockpit rejected the request: %s") % fields_detail
            return detail or _("Voxbi Cockpit rejected the request (validation error).")
        if status == 429:
            return _(
                "Too many requests to Voxbi Cockpit. Please wait a minute and try again."
            )
        return detail or (_("HTTP %s") % status)

    # --- actions ---------------------------------------------------------

    def action_install(self):
        self.ensure_one()
        if not self._cockpit_api_key():
            raise UserError(_(
                "Not connected to Voxbi Cockpit yet. Click Connect above, or "
                "paste a Cockpit API key."
            ))

        # Authorization is given on Cockpit's authorize screen, which states
        # what is sent and what is done with it before the customer clicks
        # through. A second checkbox here asked the same question twice and
        # blocked the connect flow from installing on its own.

        # Every install mints a new admin key and hands it to Cockpit, so the
        # swap back to the sync user has to run again. Without this reset a
        # re-install leaves Cockpit holding the admin credential for good.
        self.sync_user_swapped = False

        # integration-api reads this back while it provisions, to grant the
        # sync user its Voxbi group, so it has to exist before Cockpit is told
        # to start. The swap writes it again once the install succeeds.
        if self.sync_user_id:
            self.env["ir.config_parameter"].sudo().set_param(
                SYNC_USER_PARAM, str(self.sync_user_id.id)
            )

        base_url = self._cockpit_base_url()

        try:
            login, api_key = self._issue_api_key_for_current_user()
        except Exception as e:
            raise UserError(_(
                "Could not generate an Odoo API key for the current user: %s"
            ) % e)

        payload = {
            "odoo_url": self._odoo_self_url(),
            "odoo_db": self.env.cr.dbname,
            "odoo_version": self._odoo_version(),
            "service_user": login,
            "service_key": api_key,
            "service_uid": int(self.env.user.id),
            "sync_sip_configurations": bool(self.sync_sip_configurations),
            "is_active": bool(self.is_active),
            "installer_module_version": MODULE_VERSION,
        }

        url = f"{base_url}/api/v1/odoo-installer/register-install"
        _logger.info("Voxbi installer: posting register-install to %s", url)
        status, body = self._post_json(url, payload)

        if status == 201:
            self.write({
                "state": "installing",
                "integration_id": str(body.get("integration_id") or ""),
                "message": _("Voxbi module is installing. This page updates automatically."),
            })
            return True

        self.write({
            "state": "failed",
            "message": _("Register-install failed: %s") % self._api_error_message(status, body),
        })
        # Cockpit never took the key, so nothing will ever use it.
        self._revoke_installer_key()
        return True

    def action_refresh(self):
        self.ensure_one()
        if not self.integration_id:
            raise UserError(_("Nothing to refresh yet. Click Install first."))

        url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/install-status"
        status, body = self._get_json(url)

        if status == 404:
            self.write({
                "state": "failed",
                "message": _(
                    "Voxbi Cockpit has no integration registered for this API key yet. "
                    "Click Install to register it."
                ),
            })
            return True

        if status != 200:
            self.write({
                "state": "failed",
                "message": _("Status check failed: %s") % self._api_error_message(status, body),
            })
            return True

        output_html = self._render_output_html(body.get("results") or [])

        remote_status = (body.get("status") or "").lower()
        # Cockpit Integration.job_status: pending | processing | success | failed
        if remote_status == "success":
            self._swap_to_sync_user()
            # The Calls menu and the tabs on Contacts, Leads and Tasks are
            # created server-side during the install, so the browser is still
            # holding the menu it loaded before any of them existed. Nothing
            # is wrong, but without saying so the customer reads a success
            # message and then cannot find what it installed.
            reload_hint = _(
                "Refresh this page (F5) to see the Voxbi Calls menu and the "
                "Calls tabs on your contacts."
            )

            message = _("Voxbi installed successfully. %s") % reload_hint
            if self.sync_user_id and not self.sync_user_swapped:
                # The install itself succeeded; only the handoff of the sync
                # credential failed (Cockpit briefly unreachable, etc). Say so
                # and let action_open_setup retry it, rather than hiding it
                # behind a generic success message.
                message = _(
                    "Voxbi installed successfully. Handing the sync credentials "
                    "to Cockpit failed and will be retried the next time this "
                    "page is opened. %s"
                ) % reload_hint
            self.write({
                "state": "done",
                "message": message,
                "output_html": output_html,
            })
            # Cockpit now holds the sync user's key instead of the admin one.
            self._revoke_installer_key()
            # Cockpit has provisioned its own Voxbi menu by now — merge ours
            # into it so the user is not left with two "Voxbi" root menus.
            self._reconcile_voxbi_menus()
        elif remote_status == "failed":
            self.write({
                "state": "failed",
                "message": self._last_error_line(body) or _("Install failed"),
                "output_html": output_html,
            })
            # A failed install has no more use for admin rights either, and
            # leaving the key alive is the worse of the two outcomes: nothing
            # else would ever come back to clean it up.
            self._revoke_installer_key()
        else:
            step = _("Installing voxbi module") if remote_status == "processing" else _("Queued")
            self.write({
                "state": "installing",
                "message": step,
                "output_html": output_html,
            })

        return True

    @staticmethod
    def _render_output_html(results):
        """Render Voxbi Cockpit's [{color, message}, ...] log array as a styled HTML block.

        Mirrors Voxbi Cockpit's Output terminal: black background, monospace, color-coded
        lines. `color` arrives as Tailwind-ish names (text-red-500, text-blue-500,
        etc.); we map them to inline CSS colors.
        """
        if not results:
            return False

        color_map = {
            "text-red-500": "#ef4444",
            "text-orange-500": "#f97316",
            "text-yellow-500": "#eab308",
            "text-green-500": "#22c55e",
            "text-blue-500": "#60a5fa",
            "text-gray-500": "#9ca3af",
        }

        from markupsafe import escape

        lines = []
        for entry in results:
            if not isinstance(entry, dict):
                continue
            msg = entry.get("message")
            if msg is None:
                continue
            color_key = entry.get("color") or "text-blue-500"
            css = color_map.get(color_key, "#e5e7eb")
            lines.append(
                f'<div style="color:{css};white-space:pre-wrap">{escape(msg)}</div>'
            )

        if not lines:
            return False

        body = "".join(lines)
        return (
            '<div style="background:#0b0b0b;color:#e5e7eb;padding:12px;'
            'border-radius:6px;font-family:ui-monospace,Menlo,Consolas,monospace;'
            'font-size:12px;max-height:480px;overflow:auto">'
            f'{body}</div>'
        )

    @staticmethod
    def _last_error_line(body):
        results = body.get("results") or []
        for entry in reversed(results):
            if not isinstance(entry, dict):
                continue
            color = entry.get("color") or ""
            message = entry.get("message")
            if message and ("red" in color or "orange" in color):
                return message
        if results and isinstance(results[-1], dict):
            return results[-1].get("message")
        return None

    def action_reset(self):
        """Clear install state so the user can register again.

        Keeps the (reusable, long-lived) Cockpit API key on the record — only
        the consent and the per-install state are cleared.
        """
        self.ensure_one()
        self.write({
            "state": "draft",
            "consent": False,
            "integration_id": False,
            "message": False,
            "output_html": False,
        })
        # If the provisioned integration (and its menu) is gone, this brings
        # the module's own root menu back so the wizard stays reachable.
        self._reconcile_voxbi_menus()
        return True

    def action_retry_with_fresh_credentials(self):
        """Re-issue an Odoo API key and update the existing integration.

        Used when the install failed because Cockpit could not authenticate
        into Odoo (bad creds, expired key, wrong UID). We hit Cockpit's
        `update-and-fix-integration` endpoint with a freshly-minted service key
        and flip the integration back to pending. The endpoint derives the PBX
        from the Bearer API key, so no id is sent.
        """
        self.ensure_one()
        if not self.integration_id:
            raise UserError(_(
                "No integration registered yet. Paste your Cockpit API key and click Install first."
            ))

        base_url = self._cockpit_base_url()

        try:
            login, api_key = self._issue_api_key_for_current_user()
        except Exception as e:
            raise UserError(_(
                "Could not generate an Odoo API key for the current user: %s"
            ) % e)

        payload = {
            "odoo_url": self._odoo_self_url(),
            "odoo_db": self.env.cr.dbname,
            "odoo_version": self._odoo_version(),
            "service_user": login,
            "service_key": api_key,
            "service_uid": int(self.env.user.id),
            "sync_sip_configurations": bool(self.sync_sip_configurations),
            "is_active": bool(self.is_active),
            "installer_module_version": MODULE_VERSION,
        }

        url = f"{base_url}/api/v1/odoo-installer/update-and-fix-integration"
        _logger.info("Voxbi installer: posting update-and-fix-integration to %s", url)
        status, body = self._post_json(url, payload)

        if status in (200, 201):
            self.write({
                "state": "installing",
                "integration_id": str(body.get("integration_id") or self.integration_id or ""),
                "message": _("Credentials refreshed. Voxbi is retrying the install — this page updates automatically."),
            })
            return True

        if status == 404:
            self.write({
                "state": "draft",
                "integration_id": False,
                "message": _(
                    "Voxbi Cockpit no longer has an integration for this API key. "
                    "Click Install to register it again."
                ),
            })
            return True

        self.write({
            "state": "failed",
            "message": _("Credential refresh failed: %s") % self._api_error_message(status, body),
        })
        return True

    def action_fetch_integration(self):
        """Pull the current integration state from Cockpit (no secrets).

        Useful after closing/reopening the wizard to confirm what Cockpit
        currently has on file for this install — what odoo_url / service_user
        / odoo_version it's holding, and whether the integration is active.
        """
        self.ensure_one()
        if not self.integration_id:
            raise UserError(_("No integration registered yet. Click Install first."))

        url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/get-integration"
        status, body = self._get_json(url)

        if status == 404:
            raise UserError(_(
                "Voxbi Cockpit has no integration for this API key yet. Click Install first."
            ))
        if status != 200:
            raise UserError(
                _("Could not load integration from Cockpit: %s")
                % self._api_error_message(status, body)
            )

        lines = [
            _("Integration: %s") % body.get("integration_id"),
            _("Odoo URL: %s") % body.get("odoo_url"),
            _("Odoo DB: %s") % body.get("odoo_db"),
            _("Service user: %s") % body.get("service_user"),
            _("Odoo version: %s") % body.get("odoo_version"),
            _("Active: %s") % body.get("is_active"),
            _("Job status: %s") % body.get("job_status"),
        ]

        status_url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/install-status"
        status_code, status_body = self._get_json(status_url)
        output_html = False
        if status_code == 200:
            output_html = self._render_output_html(status_body.get("results") or [])

        self.write({
            "message": "\n".join(str(l) for l in lines),
            "output_html": output_html or self.output_html,
        })
        return True

    @api.model
    def action_open_setup(self):
        """Open the wizard, reusing the latest record (or creating a fresh one).

        When state=done, we still show the same record so the user sees an
        "Installed" confirmation page with a Reinstall option, rather than
        being thrown into an empty form.
        """
        rec = self.search([], order="id desc", limit=1)

        # Stale "installing" rows that never registered can't be refreshed; start fresh.
        if not rec or (rec.state == "installing" and not rec.integration_id):
            rec = self.create({})

        # A failure from a connection that no longer exists is not actionable:
        # nothing on this page can retry it, and a refresh would just redisplay
        # the error. Disconnecting already resets to draft; this catches records
        # stranded by anything that cleared the credential another way.
        if not rec.is_connected and rec.state in ("failed", "done"):
            rec.write({
                "state": "draft",
                "integration_id": False,
                "output_html": False,
                "message": False,
                # A key left in the field outlives the connection it came with,
                # and _cockpit_api_key() falls back to it -- so a dead key kept
                # being posted to register-install, which answered 401. The
                # field is no longer on screen, so nobody could clear it.
                "cockpit_api_key": False,
            })

        # Safety net for provisioning that finished while the wizard was
        # closed (the auto-refresh only polls while the form is open).
        self._reconcile_voxbi_menus()

        # Same idea for the sync-user handoff: if it failed at the moment the
        # install succeeded (Cockpit briefly unreachable), there is otherwise
        # no later trigger to retry it, since polling stops once state is
        # "done". Reopening the wizard is a reliable point to try again.
        if rec.state == "done" and not rec.sync_user_swapped:
            rec._swap_to_sync_user()

        return {
            "type": "ir.actions.act_window",
            "name": _("Voxbi Configuration"),
            "res_model": self._name,
            "res_id": rec.id,
            "view_mode": "form",
            "view_id": self.env.ref("voxbi_installer.view_voxbi_installer_setup_form").id,
            "target": "current",
        }

    # --- Cockpit connect (authorization-code) flow ------------------------

    def action_connect_cockpit(self):
        """Return an act_url sending the browser to Cockpit's consent screen.

        This method itself never calls Cockpit; Odoo only builds the URL.
        Cockpit is reached solely by the customer's own browser following
        this redirect, and it is the browser that comes back to
        /voxbi/connect/callback afterwards.
        """
        self.ensure_one()
        base_url = self._cockpit_base_url()
        query = urllib.parse.urlencode({
            "state": self._create_connect_state(),
            "redirect_uri": self._connect_redirect_uri(),
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"{base_url}{CONNECT_AUTHORIZE_PATH}?{query}",
            "target": "self",
        }

    @api.model
    def _connect_redirect_uri(self):
        return self._odoo_self_url().rstrip("/") + CONNECT_CALLBACK_PATH

    @api.model
    def _create_connect_state(self):
        """Mint a single-use, time-boxed OAuth state token.

        32 bytes of randomness, stored server side (not in the session) as an
        ir.config_parameter keyed per-state, so it survives the round trip
        through Cockpit. Consumed exactly once by `_consume_connect_state`.
        """
        state = secrets.token_urlsafe(32)
        expires_at = fields.Datetime.now() + timedelta(minutes=CONNECT_STATE_TTL_MINUTES)
        self.env["ir.config_parameter"].sudo().set_param(
            CONNECT_STATE_PARAM_PREFIX + state,
            json.dumps({"expires_at": fields.Datetime.to_string(expires_at)}),
        )
        return state

    @api.model
    def _consume_connect_state(self, state):
        """Validate a state token and consume it so it can never be reused.

        Returns True only for a state that is known and not yet expired. The
        stored parameter is deleted the moment it is looked up, whether it
        turns out to still be valid or already expired, so a replay of the
        same state always fails.
        """
        if not state:
            return False
        key = CONNECT_STATE_PARAM_PREFIX + state
        ICP = self.env["ir.config_parameter"].sudo()
        raw = ICP.get_param(key)
        if not raw:
            return False
        ICP.set_param(key, False)
        try:
            data = json.loads(raw)
            expires_at = fields.Datetime.from_string(data["expires_at"])
        except (ValueError, KeyError, TypeError):
            return False
        return fields.Datetime.now() <= expires_at

    @api.model
    def _autostart_install(self):
        """Install straight after a successful connect.

        Authorization was given on Cockpit's authorize screen, so there is
        nothing left to ask: landing on a page whose only remaining action is
        one more button makes the customer confirm the same thing twice.

        A sync user must exist BEFORE the install runs, not after. The install
        hands Cockpit an admin key and only replaces it once it succeeds, and
        that replacement is skipped when there is no sync user to swap to --
        which would leave Cockpit holding admin credentials, the exact thing
        this flow exists to avoid. action_create_sync_user is idempotent and
        reuses the existing Voxbi Sync user when there is one.

        Failures are recorded on the wizard, never raised: this runs inside
        the OAuth callback, and an exception there would show the customer a
        connect error for an install problem, with the connection already made.
        """
        record = self.search([], order="id desc", limit=1)
        if not record:
            record = self.create({})

        if not record.sync_user_id:
            record.action_create_sync_user()

        try:
            record.action_install()
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            _logger.exception("Voxbi: install could not be started after connect")
            record.write({
                "state": "failed",
                "message": _("Could not start the installation: %s") % exc,
            })
        return record

    def action_reinstall(self):
        """Re-run the whole setup: disconnect, then authorize again.

        Not a second register-install. The first install deliberately leaves
        Voxbi holding only the sync user's credential, so re-running it would
        mint fresh admin rights against a connection the customer authorized
        for something narrower. Starting from disconnect revokes both keys at
        Cockpit and here, clears the sync user parameter and resets the swap
        flag, so the customer re-authorizes with the same screen and the same
        disclosure they saw the first time.
        """
        self.ensure_one()
        self.action_disconnect()
        return self.action_connect_cockpit()

    def action_disconnect(self):
        """Withdraw the Voxbi connection, revoking rather than forgetting.

        Order matters: Cockpit is asked to revoke FIRST, and a refusal aborts
        the whole thing. Clearing locally first would leave a live credential
        with nothing left in this database that knows how to revoke it.

        Nothing is uninstalled. The Voxbi models, views and call records stay,
        so a customer who reconnects later keeps their history.
        """
        self.ensure_one()

        if not self.env.user.has_group("base.group_system"):
            raise UserError(_(
                "You are not allowed to disconnect the Voxbi connection."
            ))

        backend = self.env["voxbi.backend"].sudo().search([], limit=1, order="id asc")

        # The connect flow writes its credential onto the backend record, not
        # onto cockpit_api_key -- that field is only ever populated by the
        # older paste-a-key install flow. _post_json's own _auth_headers()
        # reads cockpit_api_key alone, so for a connect-flow customer it would
        # send no Authorization header at all, Cockpit would answer 401, and
        # the "already revoked" rule below would report success while Cockpit
        # still held a live key. Prefer the backend key; fall back to
        # cockpit_api_key so a paste-a-key install can still revoke.
        #
        # The destination host must come from that same source: the connect
        # flow never writes voxbi.cockpit_url (only the backend record's own
        # cockpit_url), so building the URL from the system parameter here
        # sends a connect-flow customer's key to whatever Cockpit that
        # parameter happens to name -- the wrong one, if it names one at all.
        # Keying the URL off wherever the credential itself came from keeps
        # them from ever pointing at two different Cockpits.
        key = (backend.api_key if backend else False) or self._cockpit_api_key()

        # With no credential at all there is nothing to revoke remotely: skip
        # the call rather than sending it unauthenticated and reading its 401
        # as a revocation that never happened. Only reached once a key exists,
        # so the base URL lookup below (and its https validation) never runs
        # needlessly on a disconnect with nothing to revoke.
        if key:
            if backend and backend.api_key:
                base_url = self._require_https_cockpit_url(
                    backend.cockpit_url, _("connected backend record")
                )
            else:
                base_url = self._cockpit_base_url()
            url = f"{base_url}/api/v1/odoo-connect/revoke"
            status, body = self._post_json_with_key(url, {}, key)

            # 401 means the key is already dead: Cockpit hard deletes the token,
            # so a second attempt cannot authenticate with it. Treat that as
            # success and carry on with local cleanup, otherwise a disconnect
            # that failed halfway can never be completed -- the customer would
            # be stuck holding a local credential Cockpit no longer honours.
            if status not in (200, 401):
                raise UserError(_(
                    "Voxbi Cockpit could not revoke the connection (%s). Nothing "
                    "was changed here, so you can try again."
                ) % self._api_error_message(status, body))

        # Only the key. cockpit_url stays: it is not a secret, keeping it
        # prefills a later reconnect, and clearing it trips the model's
        # https constraint, which rejects an empty URL.
        if backend and backend.api_key:
            backend.sudo().write({"api_key": False})

        # Both keys Voxbi minted inside this Odoo. The installer key still
        # exists here even though Cockpit stopped storing it: the swap replaced
        # Cockpit's copy, it never revoked the key itself.
        #
        # Matched by NAME and scope, never scope alone: customers have their own
        # rpc keys for unrelated integrations.
        self.env["res.users.apikeys"].sudo().search([
            ("scope", "=", API_KEY_SCOPE),
            ("name", "in", [API_KEY_NAME, SYNC_API_KEY_NAME]),
        ]).unlink()

        self.env["ir.config_parameter"].sudo().set_param(SYNC_USER_PARAM, False)

        # The sync user itself is left alone: Voxbi may have created it, but it
        # is a user in the customer's database and may own records.
        # Back to draft, and the integration id goes with it. Leaving the old
        # state behind meant a disconnected wizard kept polling install-status
        # for an install it no longer holds a credential for, and reported the
        # 401 as "your Cockpit API key is missing, invalid, or expired" -- which
        # sent the customer off to create a key the connect flow never needed.
        # It matters most on the re-install path, which disconnects first: a
        # customer who closes Cockpit's authorize screen lands back here, and
        # what they should see is the Connect button, not a failed install.
        self.write({
            "state": "draft",
            "integration_id": False,
            "output_html": False,
            "cockpit_api_key": False,
            "sync_user_swapped": False,
            "message": _("Voxbi has been disconnected."),
        })

    # --- menu reconciliation ----------------------------------------------

    @api.model
    def _reconcile_voxbi_menus(self):
        """Keep a single "Voxbi" root menu.

        Cockpit's provisioning creates its own root "Voxbi" menu (call list,
        dashboards, …). Once that exists, the module's own root menu is
        redundant: hide it and hang the Configuration entry under Cockpit's
        menu instead. Without a provisioned menu, restore the module's root.

        Idempotent. Called from a <function/> tag in the module data — i.e. on
        every install/upgrade/reinstall, right after menu.xml has re-rooted
        the menus — and again when an install round-trip completes, so a
        duplicate "Voxbi" root never survives.
        """
        root = self.env.ref("voxbi_installer.menu_voxbi_root", raise_if_not_found=False)
        setup = self.env.ref("voxbi_installer.menu_voxbi_setup", raise_if_not_found=False)
        if not root or not setup:
            return
        # full_list bypasses ir.ui.menu's visibility filtering (which hides
        # action-less/childless menus from search on Odoo <= 18).
        Menu = self.env["ir.ui.menu"].sudo().with_context(**{"ir.ui.menu.full_list": True})
        cockpit_root = Menu.search(
            [
                ("id", "!=", root.id),
                ("parent_id", "=", False),
                ("name", "=ilike", "voxbi"),
            ],
            limit=1,
        )
        if cockpit_root:
            if setup.parent_id != cockpit_root:
                setup.sudo().write({"parent_id": cockpit_root.id, "sequence": 100})
            if root.active:
                root.sudo().write({"active": False})
        else:
            if not root.active:
                root.sudo().write({"active": True})
            if setup.parent_id != root:
                setup.sudo().write({"parent_id": root.id})
