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
        "flow_webhook_env": "TEAMS_FLOW_WEBHOOK",
        "channels": {
            "others": {"display_name": "Others", "active": True},
            "utah": {"display_name": "Utah", "active": True},
            "beaver": {"display_name": "Beaver", "active": False},
        },
        "tag_groups": {
            "city_watchers": {
                "name": "City Watchers"
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
            "channel_name": "Utah",
            "tag_name": "Example City",
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def test_direct_channel_and_tag_name_work_without_config(self):
        destination = teams_notify.resolve_teams_destination(
            self.base_notification,
            environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
        )

        self.assertEqual("utah", destination["channel_key"])
        self.assertEqual("Utah", destination["channel_display_name"])
        self.assertEqual("https://teams-flow.test", destination["webhook_url"])
        self.assertFalse(destination["used_fallback"])
        self.assertEqual(["Example City"], destination["tag_names"])

    def test_config_fallback_still_works_for_legacy_route_key(self):
        destination = teams_notify.resolve_teams_destination(
            {
                **self.base_notification,
                "channel_name": None,
                "tag_name": None,
                "route_key": "beaver",
                "tag_key": "city_watchers",
            },
            teams_config_path=str(self.config_path),
            environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
        )

        self.assertEqual("others", destination["channel_key"])
        self.assertEqual("Others", destination["channel_display_name"])
        self.assertEqual("https://teams-flow.test", destination["webhook_url"])
        self.assertTrue(destination["used_fallback"])

    def test_direct_channel_and_tag_name_override_config_lookup(self):
        destination = teams_notify.resolve_teams_destination(
            {**self.base_notification, "channel_name": "Test", "tag_name": "Salt Lake City"},
            teams_config_path=str(self.config_path),
            environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
        )

        self.assertEqual("test", destination["channel_key"])
        self.assertEqual("Test", destination["channel_display_name"])
        self.assertEqual(["Salt Lake City"], destination["tag_names"])
        self.assertFalse(destination["used_fallback"])

    def test_payload_includes_card_and_delivery(self):
        destination = teams_notify.resolve_teams_destination(
            self.base_notification,
            environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
        )

        payload = teams_notify.build_adaptive_card_payload(
            self.base_notification,
            destination,
        )

        body = payload["card"]["body"]
        fact_block = next(block for block in body if block.get("type") == "FactSet")
        facts = {fact["title"]: fact["value"] for fact in fact_block["facts"]}
        self.assertEqual("2026-05-19", facts["Meeting Date:"])
        self.assertEqual("Tuesday, May 19, 2026 6:00 PM", facts["Event Date/Time:"])
        self.assertEqual("__MENTIONS__", body[0]["text"])
        self.assertEqual("Utah", payload["deliveries"][0]["channelName"])
        self.assertEqual(["Example City"], payload["deliveries"][0]["tagNames"])
        self.assertEqual("Open Source", payload["card"]["actions"][0]["title"])

    def test_entity_fallback_tag_payload_still_valid(self):
        destination = teams_notify.resolve_teams_destination(
            {**self.base_notification, "tag_name": None},
            environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
        )

        payload = teams_notify.build_adaptive_card_payload({**self.base_notification, "tag_name": None}, destination)

        self.assertEqual(["Example City"], payload["deliveries"][0]["tagNames"])
        self.assertEqual("Open Source", payload["card"]["actions"][0]["title"])

    def test_explicit_tag_name_overrides_entity_fallback(self):
        destination = teams_notify.resolve_teams_destination(
            {**self.base_notification, "tag_name": "Custom Tag"},
            environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
        )

        payload = teams_notify.build_adaptive_card_payload(
            {**self.base_notification, "tag_name": "Custom Tag"},
            destination,
        )

        self.assertEqual(["Custom Tag"], payload["deliveries"][0]["tagNames"])

    def test_send_ms_teams_message_routes_end_to_end(self):
        with patch("notifiers.teams_notify.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            teams_notify.send_ms_teams_message(
                self.base_notification,
                environ={"TEAMS_FLOW_WEBHOOK": "https://teams-flow.test"},
            )

        self.assertEqual("https://teams-flow.test", mock_post.call_args.args[0])
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual("Utah", payload["deliveries"][0]["channelName"])


if __name__ == "__main__":
    unittest.main()
