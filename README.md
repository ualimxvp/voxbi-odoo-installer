# Voxbi for Odoo

> Connect your Odoo instance to **Voxbi** telephony in a few clicks.

`voxbi_installer` is an Odoo application that bootstraps the Voxbi telephony
integration. You paste a **Voxbi Cockpit API key**, authorize the data hand-off,
and click **Install** — the module registers this instance with Voxbi Cockpit,
which then provisions and configures the full integration in your Odoo over
XML-RPC.

| | |
|------------------|-------------------------------------------------|
| **Module**       | `voxbi_installer`                               |
| **Version**      | `18.0.2.0.0`                                     |
| **Author**       | Mixvoip SA                                       |
| **Website**      | https://voxbi.com                                |
| **Support**      | support@mixvoip.com                              |
| **License**      | LGPL-3                                            |
| **Cockpit API**  | v2 (API-key / Bearer authentication)             |

---

## Compatibility

The module is **developed and released for Odoo 18.0**. Compatibility with
other releases is assessed from the code (view syntax and ORM APIs used) and is
noted below; only 18.0 is officially tested.

| Odoo series | Edition        | Status                | Notes |
|-------------|----------------|-----------------------|-------|
| **18.0**    | Community & Enterprise | ✅ **Supported (target)** | Declared in the manifest; developed and tested against this release. |
| **16.0**    | Community & Enterprise | ✅ **Supported (this branch)** | The `16.0` branch is ported for Odoo 16: the wizard views use the legacy `attrs`/`states` domain syntax, the model overrides `name_get()`, the OWL field/widget JS uses the class-descriptor form, and `res.users.apikeys._generate(scope, name)` is called via the 2-argument fallback. |
| **17.0 / 18.0** | Community & Enterprise | ↗️ **On their own branches** | The modern view expression syntax (`invisible="state != 'draft'"`), object-descriptor OWL fields, and the 3-argument `_generate(scope, name, expiration_date)` signature live on the `17.0` / `18.0` branches. Do not run this `16.0` branch on 17.0+. |
| **≤ 15.0**  | —              | ❓ **Untested**        | Not verified. Re-test the view syntax, OWL APIs, and API-key generation before use. |

**Why 16.0 is its own branch:** Odoo 17.0 removed the legacy `attrs`/`states`
view attributes in favor of direct Python expressions (`invisible="…"`,
`readonly="…"`), switched OWL field/widget registration to the object-descriptor
form, and changed `res.users.apikeys._generate` to require an `expiration_date`
argument. Odoo 16 uses the older `attrs`/`states` syntax, the class-descriptor
OWL form, and the 2-argument `_generate`. Rather than one module straddle both,
each Odoo series is maintained on its own branch.

> The integration that Voxbi Cockpit provisions over XML-RPC touches standard
> models (`res.partner`, `mail.message`, `crm.lead`, `project.task`, and
> account/sales-team groups). The manifest declares these as dependencies, so
> they must be installable on your edition.

---

## Architecture

```
┌────────────┐  1. register-install (Bearer API key)   ┌──────────────────┐
│            │ ───────────────────────────────────────▶│                  │
│   Odoo     │  2. poll install-status                 │  Voxbi Cockpit   │
│ (this app) │ ◀───────────────────────────────────────│  (Mixvoip SA)    │
│            │                                          │                  │
│            │ ◀───  3. XML-RPC: configure integration  │                  │
└────────────┘        (using the Odoo service key)      └──────────────────┘
```

1. The admin pastes a **Cockpit API key** (Bearer) into the wizard and consents.
2. The module mints a short-lived **Odoo API key** for the current user (the
   `service_key`) and `POST`s the connection details to Cockpit's
   `register-install` endpoint, authenticated with the Bearer key.
3. The module polls `install-status` until Cockpit reports `success` or `failed`.
4. Cockpit uses the `service_key` to connect back into Odoo over XML-RPC and
   configure the integration.

There are two distinct credentials, do not confuse them:

| Credential | Direction | Created by | Purpose |
|-----------|-----------|-----------|---------|
| **Cockpit API key** (Bearer) | Odoo → Cockpit | You, in Cockpit | Authenticates every request the module makes to Cockpit. |
| **Odoo service key** (`service_key`) | Cockpit → Odoo | The module, automatically | Lets Cockpit authenticate back into Odoo over XML-RPC. Never returned by any endpoint. |

---

## Prerequisites

- An Odoo 18.0 instance you administer.
- An active **Voxbi** subscription and access to **Voxbi Cockpit**.
- Outbound HTTPS connectivity from Odoo to `https://cockpit.voxbi.com`.

---

## Getting your Cockpit API key

The installer authenticates to Voxbi Cockpit with a reusable **API key**
(a Bearer token). Create one per PBX, once:

1. Log in to **Voxbi Cockpit** for your PBX: https://cockpit.voxbi.com
2. Open **Integrations** (sidebar) → **Add integration** / **Create**.
3. Set **Type** to **API key**.
4. Give it a **Name** (e.g. `Odoo Installer`). **Expiry** is optional — leave it
   empty for a key that never expires.
5. Under **Scopes**, find the **ODOO** group and tick **“Is Odoo Installer”**.
   This is the only scope the installer needs.
6. **Save.** The API key (the Bearer value) is shown **once** — copy it now and
   treat it like a password.

> The API key is bound to exactly one PBX. Every installer endpoint
> automatically operates on that PBX's Odoo integration — there is no PBX id or
> token to pass.

---

## Installation

1. Enable developer mode: **Settings → Activate Developer Mode**.
2. **Apps → Update Apps List**.
3. Search **“Voxbi”** → **Install**.
4. Open the **Voxbi → Configuration** wizard.
5. Paste your **Cockpit API key**, review the data-sharing notice, tick the
   authorization box, and click **Install**.

The wizard shows live progress and confirms once Cockpit has configured the
integration. If something fails, the output log and an actionable error message
are shown; fix the cause and use **Try again** or **Retry with refreshed
credentials**.

---

## Configuration

| Setting | Where | Default | Purpose |
|---------|-------|---------|---------|
| Cockpit base URL | `ir.config_parameter` key `voxbi.cockpit_url` | `https://cockpit.voxbi.com` | Point the module at a different Cockpit (e.g. staging). |
| Cockpit API key | Setup wizard field | — | The Bearer key used on every request. |

To override the Cockpit URL: **Settings → Technical → System Parameters**, set
`voxbi.cockpit_url`.

---

## Data shared with Voxbi Cockpit

When you click **Install** (after explicit consent), the module sends the
following to Voxbi Cockpit over HTTPS so it can configure the integration:

- This instance's public URL (`web.base.url`) and database name
- The Odoo version
- The current user's login and user id
- A freshly generated **Odoo API key** for the current user (the `service_key`)
- Your sync preferences (`sync_sip_configurations`, `is_active`)
- The installer module version (diagnostics only)

You retain ownership of your data and can revoke the generated Odoo API key at
any time from **Preferences → Account Security**. The `service_key` is
write-only on the Cockpit side and is never returned by any endpoint.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` | API key missing, invalid, or expired | Create a new API key in Cockpit and paste it again. |
| `403 Forbidden` | Key lacks the **“Is Odoo Installer”** scope, or is a user key (not a PBX key) | Enable that scope on the key in Cockpit. |
| `404 Not Found` on status/retry | No integration registered for this key yet | Click **Install** to register first. |
| `422 Unprocessable Entity` | A required field was rejected | The wizard shows which field; correct it and retry. |
| `429 Too Many Requests` | More than 30 requests/minute for this PBX | Wait a minute and try again. |
| Cockpit can't connect back to Odoo | Stale/invalid `service_key` | Use **Retry with refreshed credentials** to mint a new key and re-run. |

---

## Repository layout

```
voxbi_installer/
├── __manifest__.py
├── models/setup_wizard.py        # wizard logic + Cockpit API v2 client
├── views/
│   ├── setup_wizard_views.xml    # wizard form
│   └── menu.xml                  # Voxbi menu
├── security/ir.model.access.csv  # access rules
└── static/
    ├── description/              # App Store listing page + icon
    └── src/                      # auto-refresh + masked-field OWL widgets
```

---

## License

Licensed under **LGPL-3**. See [`LICENSE`](LICENSE).

## Support

Operated by **Mixvoip SA** — https://voxbi.com · support@mixvoip.com
