#!/usr/bin/env python3
import os, importlib, sqlite3, datetime, yaml
from pathlib import Path

DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "council.db"))
CONFIG_PATH = os.getenv("CONFIG_PATH", "cities.yaml")

def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS agendas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT,
        feed_name TEXT,
        meeting_title TEXT,
        meeting_date TEXT,
        pdf_url TEXT UNIQUE,
        local_path TEXT,
        downloaded_at TEXT,
        summarized INTEGER DEFAULT 0,
        summary_path TEXT,
        summary_timestamp TEXT
    )""")
    return conn

def log_pdf(conn, city, feed_name, title, pdf_url, local_path):
    conn.execute("""
        INSERT OR IGNORE INTO agendas
        (city, feed_name, meeting_title, pdf_url, local_path, downloaded_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (city, feed_name, title, pdf_url, local_path, datetime.datetime.now().isoformat()))
    conn.commit()

def main():
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    conn = get_db_conn()
    existing_urls = set(row[0] for row in conn.execute("SELECT pdf_url FROM agendas"))

    for city_cfg in config["cities"]:
        name = city_cfg["name"]
        scraper_name = city_cfg.get("scraper", "civicplus")
        base_url = city_cfg["base_url"]
        scraper = importlib.import_module(f"scrapers.{scraper_name}")

        print(f"\n=== Processing {name} ===")
        for feed in city_cfg["feeds"]:
            feed_name = feed["name"]
            print(f"→ Feed: {feed_name}")
            items = scraper.scrape_feed(
                feed["url"],
                base_url,
                name,
                feed_name,
                known_urls=existing_urls,
            )
            for record in items:
                log_pdf(conn, name, feed_name, record["title"], record["pdf_url"], record["local_path"])
                existing_urls.add(record["pdf_url"])

    conn.close()
    print("\n✅ Download complete.")

if __name__ == "__main__":
    main()
