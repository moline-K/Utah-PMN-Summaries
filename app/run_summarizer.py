#!/usr/bin/env python3
import os, yaml, importlib

PMN_CONFIG_PATH = os.getenv("PMN_CONFIG_PATH", "pmn_sources.yaml")


def _load_pmn_entities(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []
    entities = []
    seen = set()
    for source in config.get("sources", []):
        entity = source.get("entity")
        if not entity:
            continue
        if entity in seen:
            continue
        seen.add(entity)
        entities.append({"name": entity})
    return entities

def main():
    pmn_targets = _load_pmn_entities(PMN_CONFIG_PATH)
    if not pmn_targets:
        raise RuntimeError(f"No PMN sources found at {PMN_CONFIG_PATH}")
    targets = pmn_targets

    summarizer_name = os.getenv("SUMMARIZER_MODULE", "openai_summarizer")
    module = importlib.import_module(f"summarizers.{summarizer_name}")
    class_name = "".join([p.capitalize() for p in summarizer_name.split("_")])[:-1] + "r"
    SummarizerClass = getattr(module, class_name)
    discord_webhook = os.getenv("DISCORD_WEBHOOK") or os.getenv("DISCORD_WEBHOOK_URL")
    teams_webhook = os.getenv("MS_TEAMS_WEBHOOK_URL") or os.getenv("MS_TEAMS_WEBHOOK")
    summarizer = SummarizerClass(discord_webhook=discord_webhook, teams_webhook=teams_webhook)

    for city in targets:
        name = city["name"]
        print(f"\n=== Summarizing {name} ({summarizer_name}) ===")
        summarizer.process_unsummarized(city_filter=name)

if __name__ == "__main__":
    main()
