# Copyright 2026 Mixvoip SA
# License LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html).


def _to_odoo_datetime(value):
    """Feed timestamps are ISO 8601 with a trailing Z; Odoo wants naive UTC."""
    if not value:
        return False
    return value.replace("T", " ").replace("Z", "")[:19]


class VoxbiCallMapper:
    def __init__(self, env, backend):
        self.env = env
        self.backend_record = backend

    def values(self, record):
        """Feed payload to x_voxbi.calls field values.

        The target model is installed by Cockpit over XML-RPC, so every field
        carries the x_ prefix Odoo requires for custom fields. Relation fields
        are deliberately absent: a user links calls to leads and tickets by
        hand, and writing them here would fight that.

        Participants are handled separately by the importer, since
        x_voxbi.call_participants links back to the call by x_call_id rather
        than hanging off it as a one2many.
        """
        direct = [
            ("direction", "x_call_type"),
            ("duration", "x_duration"),
            ("billsec", "x_billsec"),
            ("phone", "x_phone"),
            ("contact_name", "x_remote_person"),
            ("contact_email", "x_email"),
            ("recording_url", "x_call_recording"),
            ("transcription", "x_transcription"),
            ("summary", "x_summary"),
            ("translation", "x_translation"),
            ("keywords", "x_keywords"),
            ("ai_categories", "x_ai_categories"),
        ]
        values = {field: record.get(key) for key, field in direct}

        # The join key. int because the Odoo field is an integer while
        # crm_messages.cdrs_id is a varchar holding digits.
        values["x_internal_id"] = int(record["cdrs_id"])

        # All three, including answered_at, which the previous mapper dropped.
        # These three are CHAR display fields, not datetimes. The feed renders
        # them the same way the push path does, so they are copied verbatim.
        # Formatting the ISO values here instead would write a different shape
        # and a different clock for the same call, and nothing would fail.
        values["x_start_time"] = record.get("started_at_display") or False
        values["x_answer_time"] = record.get("answered_at_display") or False
        values["x_end_time"] = record.get("ended_at_display") or False

        return values
