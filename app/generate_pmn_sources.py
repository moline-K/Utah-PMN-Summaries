#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

BASE_URL_DEFAULT = "https://www.utah.gov/pmn"
DEFAULT_STORAGE_ROOT = "/data/incoming/PMN"
DEFAULT_SELECTION_PATH = "pmn_selection.yaml"
DEFAULT_CHANNELS_PATH = "MS_Teams_channels.yaml"
DEFAULT_CATALOG_PATH = "data/previous work/all_bodies.json"
DEFAULT_OUTPUT_PATH = "pmn_sources.yaml"


def slugify(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def normalize_scalar(value: Any, field_name: str) -> str:
    if value is None:
        raise ValueError(f"Missing required field: {field_name}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"Missing required field: {field_name}")
    return text


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level mapping")
    return data


def load_catalog(path: str) -> Dict[Tuple[str, str], Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    records = payload.get("records", [])
    catalog = {}
    for record in records:
        entity_id = normalize_scalar(record.get("Entity_ID"), "Entity_ID")
        public_body_id = normalize_scalar(record.get("Public_Body_ID"), "Public_Body_ID")
        catalog[(entity_id, public_body_id)] = {
            "government_type": normalize_scalar(record.get("Government_Type"), "Government_Type"),
            "entity": normalize_scalar(record.get("Entity"), "Entity"),
            "public_body": normalize_scalar(record.get("Public_Body"), "Public_Body"),
        }
    return catalog


def load_channel_keys(path: str) -> set[str]:
    config = load_yaml(path)
    channels = config.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise ValueError(f"{path} must define a non-empty channels mapping")
    return {slugify(str(key)) for key in channels.keys()}


def derive_public_body_slug(entity_slug: str, public_body: str) -> str:
    public_body_slug = slugify(public_body)
    prefix = entity_slug + "_"
    if public_body_slug.startswith(prefix):
        public_body_slug = public_body_slug[len(prefix):]
    return public_body_slug or "public_body"


def build_sources(
    selection: Dict[str, Any],
    catalog: Dict[Tuple[str, str], Dict[str, str]],
    channel_keys: set[str],
    base_url: str,
    storage_root: str,
) -> List[Dict[str, str]]:
    entities = selection.get("entities", [])
    if not isinstance(entities, list):
        raise ValueError("pmn_selection.yaml must define entities as a list")

    seen_names = set()
    seen_public_body_ids = set()
    sources: List[Dict[str, str]] = []

    for entity_entry in entities:
        if not isinstance(entity_entry, dict):
            raise ValueError("Each entity entry must be a mapping")

        government_type = normalize_scalar(entity_entry.get("government_type"), "government_type").lower()
        entity_name = normalize_scalar(entity_entry.get("entity"), "entity")
        entity_id = normalize_scalar(entity_entry.get("entity_id"), "entity_id")
        county = normalize_scalar(entity_entry.get("county"), "county")
        route_key = slugify(normalize_scalar(entity_entry.get("route_key"), "route_key"))
        mention_key = entity_entry.get("mention_key")
        mention_key = slugify(str(mention_key)) if mention_key is not None and str(mention_key).strip() else None

        if route_key not in channel_keys:
            raise ValueError(f"Unknown route_key '{route_key}' for entity '{entity_name}'")

        public_bodies = entity_entry.get("public_bodies", [])
        if not isinstance(public_bodies, list) or not public_bodies:
            raise ValueError(f"Entity '{entity_name}' must define at least one public_body")

        entity_slug = slugify(entity_name)
        for public_body_entry in public_bodies:
            if not isinstance(public_body_entry, dict):
                raise ValueError(f"Entity '{entity_name}' has an invalid public_body entry")

            public_body_name = normalize_scalar(public_body_entry.get("public_body"), "public_body")
            public_body_id = normalize_scalar(public_body_entry.get("public_body_id"), "public_body_id")

            if public_body_id in seen_public_body_ids:
                raise ValueError(f"Duplicate public_body_id '{public_body_id}' in curated manifest")
            seen_public_body_ids.add(public_body_id)

            catalog_row = catalog.get((entity_id, public_body_id))
            if not catalog_row:
                raise ValueError(
                    f"Entity '{entity_name}' / public body '{public_body_name}' with IDs "
                    f"({entity_id}, {public_body_id}) was not found in the PMN catalog snapshot"
                )

            catalog_government_type = catalog_row["government_type"].lower()
            catalog_entity = catalog_row["entity"]
            catalog_public_body = catalog_row["public_body"]
            if government_type != catalog_government_type:
                raise ValueError(
                    f"Government type mismatch for entity '{entity_name}': "
                    f"selection={government_type}, catalog={catalog_government_type}"
                )
            if entity_name != catalog_entity:
                raise ValueError(
                    f"Entity name mismatch for entity_id '{entity_id}': "
                    f"selection='{entity_name}', catalog='{catalog_entity}'"
                )
            if public_body_name != catalog_public_body:
                raise ValueError(
                    f"Public body mismatch for public_body_id '{public_body_id}': "
                    f"selection='{public_body_name}', catalog='{catalog_public_body}'"
                )

            public_body_slug = public_body_entry.get("slug")
            if public_body_slug is None or not str(public_body_slug).strip():
                public_body_slug = derive_public_body_slug(entity_slug, public_body_name)
            else:
                public_body_slug = slugify(str(public_body_slug))

            source_name = f"{entity_slug}_{public_body_slug}"
            if source_name in seen_names:
                raise ValueError(f"Duplicate generated source name '{source_name}'")
            seen_names.add(source_name)

            source = {
                "name": source_name,
                "government_type": government_type,
                "entity": entity_name,
                "entity_id": entity_id,
                "public_body": public_body_name,
                "public_body_id": public_body_id,
                "base_url": base_url,
                "storage_dir": f"{storage_root.rstrip('/')}/{entity_slug}/{public_body_slug}",
                "county": county,
                "route_key": route_key,
            }
            if mention_key:
                source["mention_key"] = mention_key
            sources.append(source)

    sources.sort(key=lambda item: (item["entity"], item["public_body"]))
    return sources


def write_yaml(path: str, sources: Iterable[Dict[str, str]]) -> None:
    payload = {"sources": list(sources)}
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# Generated from pmn_selection.yaml. Manual edits will be overwritten.\n")
        yaml.safe_dump(
            payload,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate PMN source rows from a curated entity manifest.")
    parser.add_argument("--selection", default=DEFAULT_SELECTION_PATH, help="Path to pmn_selection.yaml")
    parser.add_argument("--channels", default=DEFAULT_CHANNELS_PATH, help="Path to Teams channels YAML")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG_PATH, help="Path to all_bodies.json snapshot")
    parser.add_argument("--out", default=DEFAULT_OUTPUT_PATH, help="Output PMN sources YAML path")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT, help="Base PMN URL")
    parser.add_argument("--storage-root", default=DEFAULT_STORAGE_ROOT, help="Root directory for storage_dir")
    args = parser.parse_args()

    selection = load_yaml(args.selection)
    catalog = load_catalog(args.catalog)
    channel_keys = load_channel_keys(args.channels)
    sources = build_sources(selection, catalog, channel_keys, args.base_url, args.storage_root)
    write_yaml(args.out, sources)
    print(f"Wrote {len(sources)} sources to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
