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
        """Feed payload to Odoo field values, participants included."""
        # Straight field copies, feed key on the left, Odoo field on the right.
        direct = [
            ("id", "external_id"),
            ("direction", "direction"),
            ("duration", "duration"),
            ("billsec", "billsec"),
            ("phone", "phone"),
            ("contact_name", "contact_name"),
            ("contact_email", "contact_email"),
            ("recording_url", "recording_url"),
            ("transcription", "transcription"),
            ("summary", "summary"),
            ("translation", "translation"),
            ("keywords", "keywords"),
            ("ai_categories", "ai_categories"),
        ]
        values = {odoo_field: record.get(feed_key) for feed_key, odoo_field in direct}

        values["backend_id"] = self.backend_record.id

        values["started_at"] = _to_odoo_datetime(record.get("started_at"))
        values["ended_at"] = _to_odoo_datetime(record.get("ended_at"))

        # Replace the participant set wholesale. The feed sends the full
        # participant list every time, so delete-all plus create is both
        # simpler and correct, where merging would leave stale rows behind
        # when someone drops off a call.
        commands = [(5, 0, 0)]
        for participant in record.get("participants") or []:
            commands.append(
                (
                    0,
                    0,
                    {
                        "external_id": participant.get("id"),
                        "name": participant.get("name") or False,
                        "phone": participant.get("phone") or False,
                        "email": participant.get("email") or False,
                        "internal": bool(participant.get("internal")),
                    },
                )
            )
        values["participant_ids"] = commands

        return values
