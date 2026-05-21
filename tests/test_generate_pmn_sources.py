import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import generate_pmn_sources as generator


class GeneratePmnSourcesTests(unittest.TestCase):
    def test_build_sources_inherits_entity_metadata(self):
        selection = {
            "entities": [
                {
                    "government_type": "municipality",
                    "entity": "Example City",
                    "entity_id": "100",
                    "county": "Example",
                    "route_key": "example",
                    "mention_key": "example_city",
                    "tag_key": "example_ops",
                    "public_bodies": [
                        {"public_body": "City Council", "public_body_id": "200"},
                        {"public_body": "Planning Commission", "public_body_id": "201"},
                    ],
                }
            ]
        }
        catalog = {
            ("100", "200"): {
                "government_type": "Municipality",
                "entity": "Example City",
                "public_body": "City Council",
            },
            ("100", "201"): {
                "government_type": "Municipality",
                "entity": "Example City",
                "public_body": "Planning Commission",
            },
        }

        sources = generator.build_sources(
            selection,
            catalog,
            channel_keys={"example", "others"},
            tag_keys={"example_ops"},
            base_url="https://example.test",
            storage_root="/data/incoming/PMN",
        )

        self.assertEqual(2, len(sources))
        self.assertEqual("Example", sources[0]["county"])
        self.assertEqual("example", sources[0]["route_key"])
        self.assertEqual("example_city", sources[0]["mention_key"])
        self.assertEqual("example_ops", sources[0]["tag_key"])
        self.assertEqual("100", sources[0]["entity_id"])
        self.assertEqual("/data/incoming/PMN/example_city/city_council", sources[0]["storage_dir"])
        self.assertEqual("/data/incoming/PMN/example_city/planning_commission", sources[1]["storage_dir"])

    def test_build_sources_rejects_unknown_catalog_ids(self):
        selection = {
            "entities": [
                {
                    "government_type": "municipality",
                    "entity": "Example City",
                    "entity_id": "100",
                    "county": "Example",
                    "route_key": "example",
                    "public_bodies": [
                        {"public_body": "City Council", "public_body_id": "999"},
                    ],
                }
            ]
        }
        catalog = {}

        with self.assertRaisesRegex(ValueError, "was not found in the PMN catalog snapshot"):
            generator.build_sources(
                selection,
                catalog,
                channel_keys={"example", "others"},
                tag_keys=set(),
                base_url="https://example.test",
                storage_root="/data/incoming/PMN",
            )

    def test_load_channel_keys_reads_yaml(self):
        payload = {
            "default_channel": "others",
            "channels": {
                "others": {"display_name": "Others", "active": True, "webhook_env": "OTHERS"},
                "example": {"display_name": "Example", "active": True, "webhook_env": "EXAMPLE"},
            },
            "tag_groups": {
                "example_ops": {"team_id": "team-123", "tag_id": "tag-456"},
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "channels.yaml"
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")

            keys = generator.load_channel_keys(str(path))
            tag_keys = generator.load_tag_keys(str(path))

        self.assertEqual({"others", "example"}, keys)
        self.assertEqual({"example_ops"}, tag_keys)

    def test_build_sources_rejects_unknown_tag_key(self):
        selection = {
            "entities": [
                {
                    "government_type": "municipality",
                    "entity": "Example City",
                    "entity_id": "100",
                    "county": "Example",
                    "route_key": "example",
                    "tag_key": "missing_tag",
                    "public_bodies": [
                        {"public_body": "City Council", "public_body_id": "200"},
                    ],
                }
            ]
        }
        catalog = {
            ("100", "200"): {
                "government_type": "Municipality",
                "entity": "Example City",
                "public_body": "City Council",
            }
        }

        with self.assertRaisesRegex(ValueError, "Unknown tag_key 'missing_tag'"):
            generator.build_sources(
                selection,
                catalog,
                channel_keys={"example", "others"},
                tag_keys={"example_ops"},
                base_url="https://example.test",
                storage_root="/data/incoming/PMN",
            )


if __name__ == "__main__":
    unittest.main()
