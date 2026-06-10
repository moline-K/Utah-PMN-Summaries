import sys
import unittest
from pathlib import Path

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
                    "channel_name": "Example City Alerts",
                    "tag_name": "Example City",
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
            base_url="https://example.test",
            storage_root="/data/incoming/PMN",
        )

        self.assertEqual(2, len(sources))
        self.assertNotIn("county", sources[0])
        self.assertEqual("Example City Alerts", sources[0]["channel_name"])
        self.assertEqual("Example City", sources[0]["tag_name"])
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
                    "channel_name": "Example City Alerts",
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
                base_url="https://example.test",
                storage_root="/data/incoming/PMN",
            )

    def test_build_sources_allows_optional_tag_name(self):
        selection = {
            "entities": [
                {
                    "government_type": "municipality",
                    "entity": "Example City",
                    "entity_id": "100",
                    "channel_name": "Example City Alerts",
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

        sources = generator.build_sources(
            selection,
            catalog,
            base_url="https://example.test",
            storage_root="/data/incoming/PMN",
        )
        self.assertNotIn("tag_name", sources[0])

    def test_build_sources_requires_channel_name(self):
        selection = {
            "entities": [
                {
                    "government_type": "municipality",
                    "entity": "Example City",
                    "entity_id": "100",
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

        with self.assertRaisesRegex(ValueError, "must define channel_name"):
            generator.build_sources(
                selection,
                catalog,
                base_url="https://example.test",
                storage_root="/data/incoming/PMN",
            )


if __name__ == "__main__":
    unittest.main()
