{
    "name": "Voxbi Installer",
    "summary": "Connect this Odoo to Mixvoip Voxbi telephony.",
    "description": """
Voxbi Installer
===============
Paste a one-time install token from Mixvoip Cockpit and click Install.
This module hands off connection details to Mixvoip Cockpit, which then
installs and configures the full Voxbi telephony integration in this Odoo
over XML-RPC.

""",
    "author": "Mixvoip",
    "website": "https://www.mixvoip.com",
    "category": "Telephony",
    "version": "18.0.0.15.0",
    "license": "LGPL-3",
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/setup_wizard_views.xml",
        "views/menu.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
