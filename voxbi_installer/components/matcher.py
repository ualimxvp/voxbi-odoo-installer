# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from ..utils.phone import normalise_number


class VoxbiPartnerMatcher:
    """Finds the res.partner a call belongs to.

    Runs entirely inside the customer's database. No contact data is sent to
    Voxbi, which is the property that lets us say their data never leaves.
    """

    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend

    def find_partner(self, phone, email=None):
        key = normalise_number(phone)
        if key:
            # Odoo 19 dropped res.partner.mobile: a contact has one phone
            # field now, so there is no second number to check here. Earlier
            # versions of this module search phone and mobile both.
            partners = self.env["res.partner"].search([("phone", "!=", False)])
            for partner in partners:
                for candidate in (partner.phone,):
                    if candidate and normalise_number(candidate) == key:
                        return partner

        if email:
            partner = self.env["res.partner"].search(
                [("email", "=ilike", email)], limit=1
            )
            if partner:
                return partner

        return self.env["res.partner"].browse()
