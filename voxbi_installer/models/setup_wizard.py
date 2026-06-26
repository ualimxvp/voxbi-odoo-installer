# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import json
import logging
import urllib.error
import urllib.request

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
# Version of *this* installer module, sent to Cockpit purely for diagnostics.
MODULE_VERSION = "2.0.0"


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

    @api.depends("state")
    def _compute_display_name(self):
        # Without a name/_rec_name the breadcrumb falls back to "model,id"
        # (e.g. "voxbi.installer.setup,1"). Give it a stable human label.
        for record in self:
            record.display_name = _("Voxbi Setup")

    # --- helpers ---------------------------------------------------------

    def _cockpit_base_url(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "voxbi.cockpit_url", DEFAULT_COCKPIT_URL
        ).rstrip("/")

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
        # Wipe any prior keys for this scope so revocation/rotation is clean.
        ApiKeys = self.env["res.users.apikeys"].sudo()
        prior = ApiKeys.search([
            ("user_id", "=", user.id),
            ("scope", "=", API_KEY_SCOPE),
        ])
        if prior:
            prior.unlink()

        plaintext = self._generate_api_key(API_KEY_SCOPE, API_KEY_NAME)
        return user.login, plaintext

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
            self.write({
                "state": "done",
                "message": _("Voxbi installed successfully."),
                "output_html": output_html,
            })
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

        return {
            "type": "ir.actions.act_window",
            "name": _("Voxbi Configuration"),
            "res_model": self._name,
            "res_id": rec.id,
            "view_mode": "form",
            "view_id": self.env.ref("voxbi_installer.view_voxbi_installer_setup_form").id,
            "target": "current",
        }
