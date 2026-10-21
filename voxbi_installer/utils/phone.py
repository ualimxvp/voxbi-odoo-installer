# Copyright 2026 VOXBI S.A.
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).

import re

# Anything after these markers is an extension, not part of the number.
EXTENSION_MARKERS = re.compile(r"(?:ext\.?|x|poste)\s*\d+\s*$", re.IGNORECASE)
NON_DIGITS = re.compile(r"\D")

DEFAULT_COUNTRY_CODE = "352"
# Luxembourg national numbers are 6 to 9 digits after the country code, so a
# stripped number shorter than this is not a national number missing a prefix.
MIN_NATIONAL_LENGTH = 6


def normalise_number(raw, default_country_code=DEFAULT_COUNTRY_CODE):
    """Reduce a phone number to a digits-only comparison key.

    Handles the shapes the same number arrives in: E.164 (+352...),
    international prefix (00352...), bare country code (352...) and national
    with a trunk zero (0661...). A leading + or 00 means the number already
    carries its own country code, so nothing is prepended. Returns "" when
    there is nothing to compare.
    """
    if not raw:
        return ""

    text = str(raw).strip()
    without_extension = EXTENSION_MARKERS.sub("", text)
    digits = NON_DIGITS.sub("", without_extension)
    if not digits:
        return ""

    # Check these before falling through to the national branch: NON_DIGITS
    # has already destroyed the +, so the original text is the only place the
    # international marker survives.
    if text.startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]

    if digits.startswith(default_country_code):
        return digits

    # National form with a trunk zero, for example 0661123456.
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) >= MIN_NATIONAL_LENGTH:
        return default_country_code + digits
    return digits
