{
    "name": "Voxbi",
    "summary": "Connect this Odoo to Voxbi telephony.",
    "description": """
Voxbi
=====
Paste a one-time install token from Voxbi Cockpit and click Install.
This module hands off connection details to Voxbi Cockpit, which then
installs and configures the full Voxbi telephony integration in this Odoo
over XML-RPC.

This module requires Voxbi Cockpit, an external service operated by
Mixvoip SA, and an active Voxbi subscription. On install (with the
administrator's explicit consent) it sends a generated Odoo API key and
this instance's connection details to Voxbi Cockpit over HTTPS so the
integration can be configured. See the app description for the full list
of data shared.

""",
    "author": "Mixvoip SA",
    "website": "https://voxbi.com",
    "support": "support@mixvoip.com",
    "category": "Telephony",
    "version": "18.0.1.0.0",
    "license": "Other OSI approved licence",  # MIT, see LICENSE file
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
        "security/ir.model.access.csv",
        "views/setup_wizard_views.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "voxbi_installer/static/src/auto_refresh.js",
            "voxbi_installer/static/src/auto_refresh.xml",
            "voxbi_installer/static/src/masked_field.js",
            "voxbi_installer/static/src/masked_field.xml",
        ],
    },
    "application": True,
    "installable": True,
    "auto_install": False,
}
