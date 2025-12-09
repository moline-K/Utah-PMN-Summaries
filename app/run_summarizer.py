#!/usr/bin/env python3
import os, yaml, importlib

CONFIG_PATH = os.getenv("CONFIG_PATH", "cities.yaml")

def main():
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)

    for city in config["cities"]:
        name = city["name"]
        summarizer_name = city.get("summarizer", "openai_summarizer")
        module = importlib.import_module(f"summarizers.{summarizer_name}")
        class_name = "".join([p.capitalize() for p in summarizer_name.split("_")])[:-1] + "r"  # e.g. openai_summarizer -> OpenaiSummarizer
        SummarizerClass = getattr(module, class_name)
        webhook_env = city.get("discord_webhook_env")
        discord_webhook = None
        if webhook_env:
            discord_webhook = os.getenv(webhook_env)
        if not discord_webhook:
            discord_webhook = city.get("discord_webhook")
        summarizer = SummarizerClass(discord_webhook=discord_webhook)
        print(f"\n=== Summarizing {name} ({summarizer_name}) ===")
        summarizer.process_unsummarized(city_filter=name)

if __name__ == "__main__":
    main()
