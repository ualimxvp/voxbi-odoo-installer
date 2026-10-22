# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).
{
    "name": "Voxbi",
    "summary": "Voxbi cloud phone system for Odoo: call logging, click-to-call, caller details.",
    "description": """
Voxbi
=====
Voxbi is a cloud phone system, hosted in the European Union, with a native VoIP
integration for Odoo: automatic call logging, click-to-call, caller details on
screen, and AI transcripts and summaries on every call. It is built and supported
by Mixvoip, a Luxembourg telecom operator building European telecom since 2008,
and is used by more than 5,000 businesses across 26 countries.

Paste your Voxbi Cockpit API key (a reusable Bearer key with the
"Is Odoo Installer" scope) and click Install. This module hands off
connection details to Voxbi Cockpit, which then installs and configures
the full Voxbi telephony integration in this Odoo over XML-RPC.

This module requires Voxbi Cockpit, an external service operated by
VOXBI S.A., and an active Voxbi subscription. On install (with the
administrator's explicit consent) it sends a generated Odoo API key and
this instance's connection details to Voxbi Cockpit over HTTPS so the
integration can be configured. See the app description for the full list
of data shared.

""",
    "author": "VOXBI S.A.",
    "website": "https://voxbi.com",
    "support": "hello@voxbi.com",
    "category": "Telephony",
    "version": "19.0.3.0.0",
    "license": "LGPL-3",
    # Prerequisite apps for the Voxbi integration that Cockpit pushes over
    # XML-RPC: the integration touches res.partner, mail.message, crm.lead,
    # project.task and account/sales_team groups, so those models must exist
    # before the push. Community-installable modules only.
    #
    # Enterprise-only modules the integration *optionally* uses are NOT listed
    # here — they are absent on OCB/community and would block install, and the
    # integration applies them conditionally at runtime (guarded by
    # isModuleInstalled checks):
    #   - voip        : integration stores calls in its own x_voxbi.calls model
    #   - helpdesk    : community alt is OCA helpdesk_mgmt (separate setup)
    #   - web_studio  : design-time only; x_ models run without the editor
    "depends": ["base", "web", "mail", "account", "sales_team", "crm", "project"],
    "data": [
        "security/voxbi_security.xml",
        "security/ir.model.access.csv",
        "security/voxbi_record_rules.xml",
        "views/setup_wizard_views.xml",
        "views/voxbi_backend_views.xml",
        "views/menu.xml",
        "data/reconcile_menus.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "voxbi_installer/static/src/auto_refresh.js",
            "voxbi_installer/static/src/auto_refresh.xml",
            "voxbi_installer/static/src/masked_field.js",
            "voxbi_installer/static/src/masked_field.xml",
        ],
    },
    "images": ["static/description/s1-brand.gif"],
    "application": True,
    "installable": True,
    "auto_install": False,
}
