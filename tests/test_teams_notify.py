import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from notifiers import teams_notify


def write_channels_config(path):
    payload = {
        "default_channel": "others",
        "channels": {
            "others": {"display_name": "Others", "active": True, "webhook_env": "OTHERS_CHANNEL_WEBHOOK"},
            "utah": {"display_name": "Utah", "active": True, "webhook_env": "UTAH_CHANNEL_WEBHOOK"},
            "beaver": {"display_name": "Beaver", "active": False, "webhook_env": "BEAVER_CHANNEL_WEBHOOK"},
        },
        "mention_groups": {
            "city_watchers": {
                "mode": "users",
                "users": [
                    {"name": "Alice Example", "upn": "alice@example.com"},
                ],
            }
        },
        "tag_groups": {
            "city_watchers": {
                "name": "City Watchers",
                "team_id": "team-123",
                "tag_id": "tag-456",
            }
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


class TeamsNotifyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.tempdir.name) / "channels.yaml"
        write_channels_config(self.config_path)
        self.base_notification = {
            "title": "City Council Agenda",
            "city": "Example City",
            "feed": "City Council",
            "meeting_date": "2026-05-19",
            "event_datetime_raw": "Tuesday, May 19, 2026 6:00 PM",
            "summarized_at": "2026-05-19T18:30",
            "source_url": "https://example.test/source.pdf",
            "summary_excerpt": "## Key Engineering Actions\n- Replace water line\n",
            "route_key": "utah",
            "tag_key": "city_watchers",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def test_active_route_uses_route_webhook(self):
        destination = teams_notify.resolve_teams_destination(
            self.base_notification,
            teams_config_path=str(self.config_path),
            environ={
                "OTHERS_CHANNEL_WEBHOOK": "https://others.test",
                "UTAH_CHANNEL_WEBHOOK": "https://utah.test",
            },
        )

        self.assertEqual("utah", destination["channel_key"])
        self.assertEqual("https://utah.test", destination["webhook_url"])
        self.assertFalse(destination["used_fallback"])

    def test_inactive_route_falls_back_to_default(self):
        destination = teams_notify.resolve_teams_destination(
            {**self.base_notification, "route_key": "beaver"},
            teams_config_path=str(self.config_path),
            environ={
                "OTHERS_CHANNEL_WEBHOOK": "https://others.test",
                "UTAH_CHANNEL_WEBHOOK": "https://utah.test",
            },
        )

        self.assertEqual("others", destination["channel_key"])
        self.assertEqual("https://others.test", destination["webhook_url"])
        self.assertTrue(destination["used_fallback"])

    def test_missing_route_webhook_falls_back_to_default(self):
        destination = teams_notify.resolve_teams_destination(
            self.base_notification,
            teams_config_path=str(self.config_path),
            environ={"OTHERS_CHANNEL_WEBHOOK": "https://others.test"},
        )

        self.assertEqual("others", destination["channel_key"])
        self.assertEqual("https://others.test", destination["webhook_url"])
        self.assertTrue(destination["used_fallback"])

    def test_payload_includes_meeting_date_mentions_and_tag_metadata(self):
        destination = teams_notify.resolve_teams_destination(
            {**self.base_notification, "mention_key": "city_watchers"},
            teams_config_path=str(self.config_path),
            environ={
                "OTHERS_CHANNEL_WEBHOOK": "https://others.test",
                "UTAH_CHANNEL_WEBHOOK": "https://utah.test",
            },
        )

        payload = teams_notify.build_adaptive_card_payload(
            {**self.base_notification, "mention_key": "city_watchers"},
            destination,
        )

        body = payload["attachments"][0]["content"]["body"]
        fact_block = next(block for block in body if block.get("type") == "FactSet")
        facts = {fact["title"]: fact["value"] for fact in fact_block["facts"]}
        self.assertEqual("2026-05-19", facts["Meeting Date:"])
        self.assertEqual("Tuesday, May 19, 2026 6:00 PM", facts["Event Date/Time:"])
        self.assertIn("msteams", payload["attachments"][0]["content"])
        self.assertEqual("tag-456", payload["tagId"])
        self.assertEqual("team-123", payload["teamId"])
        self.assertEqual("City Watchers", payload["tagName"])
        self.assertEqual("city_watchers", payload["tagKey"])
        self.assertEqual(
            "alice@example.com",
            payload["attachments"][0]["content"]["msteams"]["entities"][0]["mentioned"]["id"],
        )

    def test_no_mention_payload_still_valid(self):
        destination = teams_notify.resolve_teams_destination(
            self.base_notification,
            teams_config_path=str(self.config_path),
            environ={
                "OTHERS_CHANNEL_WEBHOOK": "https://others.test",
                "UTAH_CHANNEL_WEBHOOK": "https://utah.test",
            },
        )

        payload = teams_notify.build_adaptive_card_payload(self.base_notification, destination)

        self.assertNotIn("msteams", payload["attachments"][0]["content"])
        self.assertEqual("tag-456", payload["tagId"])
        self.assertEqual("Open Source", payload["attachments"][0]["content"]["actions"][0]["title"])

    def test_send_ms_teams_message_routes_end_to_end(self):
        with patch("notifiers.teams_notify.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            teams_notify.send_ms_teams_message(
                self.base_notification,
                teams_config_path=str(self.config_path),
                environ={
                    "OTHERS_CHANNEL_WEBHOOK": "https://others.test",
                    "UTAH_CHANNEL_WEBHOOK": "https://utah.test",
                },
            )

        self.assertEqual("https://utah.test", mock_post.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
