# Copyright 2026 Mixvoip SA
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

    def name_get(self):
        # Without a name/_rec_name the breadcrumb falls back to "model,id"
        # (e.g. "voxbi.installer.setup,1"). Give it a stable human label.
        # Odoo 16 derives display_name from name_get (see _compute_display_name),
        # so overriding name_get is the idiomatic way to customise it here.
        return [(record.id, _("Voxbi Setup")) for record in self]

    # --- helpers ---------------------------------------------------------

    def _cockpit_base_url(self):
        url = (self.env["ir.config_parameter"].sudo().get_param(
            "voxbi.cockpit_url", DEFAULT_COCKPIT_URL
        ) or "").strip().rstrip("/")
        # The Cockpit Bearer key and a freshly minted Odoo service key are sent
        # to this host, so refuse anything that isn't a plain https:// URL. This
        # blocks file://, http:// and SSRF to internal/metadata endpoints even
        # if the system parameter is tampered with.
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise UserError(_(
                "The Voxbi Cockpit URL (system parameter “voxbi.cockpit_url”) must "
                "be a valid https:// URL. Current value: %s"
            ) % (url or _("empty")))
        return url

    def _odoo_self_url(self):
        return self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

    def _odoo_version(self):
        # e.g. "18.0", "17.0" (or "saas~17.4" on Odoo Online). Stays within
        # Cockpit's 16-char odoo_version limit and is always the real version.
        return release.major_version

    def _cockpit_api_key(self):
        return (self.cockpit_api_key or "").strip()

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
                "Your Cockpit API key is missing, invalid, or expired. Create a new "
                "API key in Voxbi Cockpit (Integrations → Add integration → API key) "
                "with the “Is Odoo Installer” scope, paste it above, and try again."
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
            raise UserError(_("Please paste the Cockpit API key from Voxbi Cockpit."))
        if not self.consent:
            raise UserError(_(
                "Please review the data-sharing notice and tick the authorization "
                "box before installing."
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
            message = _("Voxbi installed successfully.")
            if self.sync_user_id and not self.sync_user_swapped:
                # The install itself succeeded; only the handoff of the sync
                # credential failed (Cockpit briefly unreachable, etc). Say so
                # and let action_open_setup retry it, rather than hiding it
                # behind a generic success message.
                message = _(
                    "Voxbi installed successfully. Handing the sync credentials "
                    "to Cockpit failed and will be retried the next time this "
                    "page is opened."
                )
            self.write({
                "state": "done",
                "message": message,
                "output_html": output_html,
            })
            # Cockpit has provisioned its own Voxbi menu by now — merge ours
            # into it so the user is not left with two "Voxbi" root menus.
            self._reconcile_voxbi_menus()
        elif remote_status == "failed":
            self.write({
                "state": "failed",
                "message": self._last_error_line(body) or _("Install failed"),
                "output_html": output_html,
            })
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

        # Container styling lives in the .o_voxbi_output class (output_log.css)
        # rather than inline: Odoo 16's Html-field sanitizer strips background,
        # overflow and max-height from inline styles, but keeps class names.
        body = "".join(lines)
        return f'<div class="o_voxbi_output">{body}</div>'

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
