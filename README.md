# Voxbi

Odoo Apps Store module that connects an Odoo instance to Mixvoip Voxbi telephony.

It adds a **Voxbi → Setup** wizard where you paste a one-time install token issued
from Mixvoip Cockpit. The module hands the connection details back to Cockpit, which
then installs and configures the full Voxbi telephony integration in this Odoo.

- **Odoo:** 18.0
- **Version:** 18.0.1.0.0
- **License:** MIT (see [LICENSE](LICENSE))

## Contents

```
voxbi_installer/
├── __manifest__.py
├── models/setup_wizard.py       # setup wizard + token handoff
├── views/                       # wizard view + Voxbi menu
├── static/description/          # index.html listing page + icon
└── security/                    # access rules
```

## Install in Odoo

1. Enable developer mode: **Settings → Activate Developer Mode**.
2. **Apps → Update Apps List**.
3. Search **"Voxbi"** → **Install**.
4. Open **Voxbi → Configuration**, paste your install token, review the data-sharing
   notice and tick the authorization box, then click **Install**.

The wizard shows progress and completes once Cockpit has configured the integration.

## Getting an install token

In Mixvoip Cockpit, open the user's settings page and go to the **Odoo installer**
tab, then generate a token under **Odoo install tokens**. Paste it into the setup
wizard. Tokens are single-use (and can be revoked at any time) — mint a fresh one if
the wizard reports an invalid or already-used token.
