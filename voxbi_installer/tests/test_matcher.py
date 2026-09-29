# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

from odoo.tests.common import tagged

from ..components.importer import VoxbiCallImporter
from ..utils.phone import normalise_number
from .common import VoxbiConnectorCase, call_payload


@tagged("post_install", "-at_install")
class TestNormalise(VoxbiConnectorCase):
    def test_variants_reduce_to_the_same_key(self):
        expected = normalise_number("+352661123456")
        for variant in [
            "00352661123456",
            "+352 661 123 456",
            "352-661-123456",
            "0661123456",
        ]:
            self.assertEqual(
                normalise_number(variant), expected, f"failed on {variant}"
            )

    def test_extension_is_stripped(self):
        self.assertEqual(
            normalise_number("+352661123456 ext. 22"),
            normalise_number("+352661123456"),
        )

    def test_empty_input_yields_empty_key(self):
        self.assertEqual(normalise_number(""), "")
        self.assertEqual(normalise_number(None), "")

    def test_a_foreign_number_keeps_its_own_country_code(self):
        self.assertEqual(normalise_number("+33612345678"), "33612345678")
        self.assertEqual(normalise_number("0033612345678"), "33612345678")

    def test_a_foreign_number_is_not_given_the_default_prefix(self):
        key = normalise_number("+33612345678")
        self.assertFalse(key.startswith("352"))


@tagged("post_install", "-at_install")
class TestMatcher(VoxbiConnectorCase):
    # x_voxbi.calls.x_partner_id is a stored compute field on the installed
    # target model, derived from x_remote_person_number / x_remote_person_email
    # rather than from a value the importer can write. So these exercise the
    # matcher directly against a call payload's own fields, the same way the
    # two tests below do, instead of asserting on call.x_partner_id.
    def test_import_links_a_partner_whose_number_matches(self):
        partner = self.env["res.partner"].create(
            {"name": "Anne Weber", "phone": "00352 661 123 456"}
        )
        payload = call_payload()
        matcher = VoxbiCallImporter(self.env, self.backend).matcher
        found = matcher.find_partner(payload["phone"], payload["contact_email"])
        self.assertEqual(found, partner)

    def test_no_match_leaves_partner_empty(self):
        matcher = VoxbiCallImporter(self.env, self.backend).matcher
        found = matcher.find_partner("+3529999999", None)
        self.assertFalse(found)

    def test_email_fallback_only_fires_when_number_fails(self):
        self.env["res.partner"].create(
            {"name": "Anne Weber", "phone": "00352 661 123 456"}
        )
        by_email = self.env["res.partner"].create(
            {"name": "Bernd Muller", "email": "Bernd@Example.LU"}
        )
        matcher = VoxbiCallImporter(self.env, self.backend).matcher
        found = matcher.find_partner("+3529999999", "bernd@example.lu")
        self.assertEqual(found, by_email)

    def test_email_fallback_is_skipped_when_number_matches(self):
        by_number = self.env["res.partner"].create(
            {"name": "Anne Weber", "phone": "00352 661 123 456"}
        )
        self.env["res.partner"].create(
            {"name": "Bernd Muller", "email": "anne@example.lu"}
        )
        matcher = VoxbiCallImporter(self.env, self.backend).matcher
        found = matcher.find_partner("+352661123456", "anne@example.lu")
        self.assertEqual(found, by_number)
