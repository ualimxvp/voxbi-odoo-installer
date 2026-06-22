import json
import logging
import urllib.error
import urllib.request

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Default Cockpit endpoint baked into the module. Override per-instance via
# the ir.config_parameter "voxbi.cockpit_url" (e.g. for staging).
DEFAULT_COCKPIT_URL = "https://cockpit.voxbi.com"
# Must be exactly "rpc" — that's the scope Odoo's _check_credentials fallback
# in res.users.apikeys looks for when authenticating XML-RPC requests.
API_KEY_SCOPE = "rpc"
API_KEY_NAME = "Voxbi installer"
ODOO_VERSION = "18"
MODULE_VERSION = "0.6.0"


class VoxbiInstallerSetup(models.Model):
    _name = "voxbi.installer.setup"
    _description = "Voxbi Setup"
    _order = "id desc"

    install_token = fields.Char(string="Cockpit token", required=False)
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
    token_id = fields.Char(readonly=True)
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

    def _issue_api_key_for_current_user(self):
        """Generate a fresh Odoo API key for the logged-in user.

        The customer is never asked for credentials — the wizard runs as a
        logged-in admin, so we mint an API key on their behalf via
        `res.users.apikeys` and hand the plaintext (returned once) to Voxbi
        Cockpit, which uses it as the XML-RPC password.
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

        Odoo 18 requires `expiration_date` (third arg). Falsy = persistent key,
        which is what we want here (the installer needs ongoing access).
        Sudo lets us mint a persistent key even when the user's group caps the
        max duration.
        """
        ApiKeys = self.env["res.users.apikeys"].sudo()
        try:
            return ApiKeys._generate(scope, name, False)
        except TypeError:
            # Older Odoo 18 builds without expiration_date arg.
            return ApiKeys._generate(scope, name)

    def _post_json(self, url, payload, timeout=15):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
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
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return resp.getcode(), json.loads(body)
        except urllib.error.HTTPError as e:
            return e.code, {}
        except urllib.error.URLError as e:
            return 0, {"error": "network", "reason": str(e)}

    # --- actions ---------------------------------------------------------

    def action_install(self):
        self.ensure_one()
        if not self.install_token:
            raise UserError(_("Please paste the install token from Voxbi Cockpit."))
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
            "token": self.install_token.strip(),
            "odoo_url": self._odoo_self_url(),
            "odoo_db": self.env.cr.dbname,
            "odoo_version": ODOO_VERSION,
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

        if status == 201 and "token_id" in body:
            self.write({
                "state": "installing",
                "token_id": str(body["token_id"]),
                "integration_id": str(body.get("integration_id") or ""),
                "message": _("Voxbi module is installing. This page updates automatically."),
            })
            return True

        reason = body.get("reason") or body.get("error") or f"HTTP {status}"
        token_problems = {"unknown", "expired", "consumed", "revoked"}

        if status in (401, 410) and reason in token_problems:
            # Keep the pasted token in the field — don't wipe what the user
            # entered. Surface it as a failure so the error state is obvious;
            # they paste a fresh token and click Try again.
            self.write({
                "state": "failed",
                "message": _(
                    "This install token is %(reason)s. Generate a fresh one in Voxbi "
                    "Cockpit (user's settings page → Odoo installer tab → Odoo install "
                    "tokens), paste it above, and click Try again."
                ) % {"reason": reason},
            })
        else:
            self.write({
                "state": "failed",
                "message": _("Register-install failed: %s") % reason,
            })

        return True

    def action_refresh(self):
        self.ensure_one()
        if not self.token_id:
            raise UserError(_("Nothing to refresh yet."))

        url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/install-status/{self.token_id}"
        status, body = self._get_json(url)

        if status != 200:
            self.write({"state": "failed", "message": f"Status check HTTP {status}"})
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
        """Clear state so the user can paste a fresh token and try again."""
        self.ensure_one()
        self.write({
            "state": "draft",
            "install_token": False,
            "consent": False,
            "token_id": False,
            "integration_id": False,
            "message": False,
        })
        return True

    def action_retry_with_fresh_credentials(self):
        """Re-issue an Odoo API key and PATCH the existing integration.

        Used when the install failed because crmapi could not authenticate
        into Odoo (bad creds, expired key, wrong UID). The token_id stays the
        same — we hit Voxbi Cockpit's `update-and-fix-integration` endpoint with a
        freshly-minted key and flip the integration back to pending.
        """
        self.ensure_one()
        if not self.token_id:
            raise UserError(_(
                "No integration linked to this wizard yet. Paste a token and click Install first."
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
            "odoo_version": ODOO_VERSION,
            "service_user": login,
            "service_key": api_key,
            "service_uid": int(self.env.user.id),
            "sync_sip_configurations": bool(self.sync_sip_configurations),
            "is_active": bool(self.is_active),
            "installer_module_version": MODULE_VERSION,
        }

        url = f"{base_url}/api/v1/odoo-installer/update-and-fix-integration/{self.token_id}"
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
                "install_token": False,
                "token_id": False,
                "integration_id": False,
                "message": _(
                    "Cockpit no longer recognises this install. Paste a fresh token from "
                    "Voxbi Cockpit and click Install."
                ),
            })
            return True

        reason = body.get("reason") or body.get("error") or f"HTTP {status}"
        self.write({
            "state": "failed",
            "message": _("Credential refresh failed: %s") % reason,
        })
        return True

    def action_fetch_integration(self):
        """Pull the current integration state from cockpit (no secrets).

        Useful after closing/reopening the wizard to confirm what cockpit
        currently has on file for this install — what odoo_url / service_user
        / odoo_version it's holding, and whether the integration is active.
        """
        self.ensure_one()
        if not self.token_id:
            raise UserError(_("No install token on this record yet."))

        url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/get-integration/{self.token_id}"
        status, body = self._get_json(url)

        if status != 200:
            raise UserError(_("Could not load integration from cockpit (HTTP %s).") % status)

        lines = [
            _("Integration: %s") % body.get("integration_id"),
            _("Odoo URL: %s") % body.get("odoo_url"),
            _("Odoo DB: %s") % body.get("odoo_db"),
            _("Service user: %s") % body.get("service_user"),
            _("Odoo version: %s") % body.get("odoo_version"),
            _("Active: %s") % body.get("is_active"),
            _("Job status: %s") % body.get("job_status"),
        ]

        status_url = f"{self._cockpit_base_url()}/api/v1/odoo-installer/install-status/{self.token_id}"
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

        # Stale "installing" rows with no token_id can't be refreshed; start fresh.
        if not rec or (rec.state == "installing" and not rec.token_id):
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

