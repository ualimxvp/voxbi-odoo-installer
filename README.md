# Voxbi Installer

Odoo Apps Store module that connects an Odoo instance to Mixvoip Voxbi telephony.

It adds a **Voxbi → Setup** wizard where you paste a one-time install token issued
from Mixvoip Cockpit. The module hands the connection details back to Cockpit, which
then installs and configures the full Voxbi telephony integration in this Odoo.

- **Odoo:** 18.0
- **Version:** 18.0.0.15.0
- **License:** MIT (see [LICENSE](LICENSE))

## Contents

```
voxbi_installer/
├── __manifest__.py
├── models/setup_wizard.py     # setup wizard + token handoff
├── views/                     # wizard view + Voxbi menu
└── security/                  # access rules
```

## Install in Odoo

1. Enable developer mode: **Settings → Activate Developer Mode**.
2. **Apps → Update Apps List**.
3. Search **"Voxbi Installer"** → **Install**.
4. Open **Voxbi → Setup**, paste your install token, and click **Install**.

The wizard shows progress and completes once Cockpit has configured the integration.

## Getting an install token

Generate a one-time install token from Mixvoip Cockpit and paste it into the setup
wizard. Tokens are single-use and expire — mint a fresh one if the wizard reports an
invalid or already-used token.
