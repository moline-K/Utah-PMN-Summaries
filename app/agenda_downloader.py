#!/usr/bin/env python3
import os, sqlite3, datetime, yaml
from scrapers import utah_pmn

DATA_DIR = os.getenv("DATA_DIR", "/data")
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "utah_pmn.db"))
PMN_CONFIG_PATH = os.getenv("PMN_CONFIG_PATH", "pmn_sources.yaml")

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
        summary_timestamp TEXT,
        notice_id TEXT,
        notice_url TEXT,
        source_name TEXT,
        government_type TEXT,
        entity TEXT,
        entity_id TEXT,
        public_body TEXT,
        public_body_id TEXT,
        county TEXT,
        route_key TEXT,
        mention_key TEXT,
        attachment_category TEXT,
        attachment_date_added TEXT,
        event_datetime_raw TEXT
        ,notice_tags TEXT
        ,description_agenda TEXT
        ,attachment_count INTEGER
        ,attachment_urls TEXT
    )""")
    _ensure_column(conn, "agendas", "notice_id", "TEXT")
    _ensure_column(conn, "agendas", "notice_url", "TEXT")
    _ensure_column(conn, "agendas", "source_name", "TEXT")
    _ensure_column(conn, "agendas", "government_type", "TEXT")
    _ensure_column(conn, "agendas", "entity", "TEXT")
    _ensure_column(conn, "agendas", "entity_id", "TEXT")
    _ensure_column(conn, "agendas", "public_body", "TEXT")
    _ensure_column(conn, "agendas", "public_body_id", "TEXT")
    _ensure_column(conn, "agendas", "county", "TEXT")
    _ensure_column(conn, "agendas", "route_key", "TEXT")
    _ensure_column(conn, "agendas", "mention_key", "TEXT")
    _ensure_column(conn, "agendas", "attachment_category", "TEXT")
    _ensure_column(conn, "agendas", "attachment_date_added", "TEXT")
    _ensure_column(conn, "agendas", "event_datetime_raw", "TEXT")
    _ensure_column(conn, "agendas", "notice_tags", "TEXT")
    _ensure_column(conn, "agendas", "description_agenda", "TEXT")
    _ensure_column(conn, "agendas", "attachment_count", "INTEGER")
    _ensure_column(conn, "agendas", "attachment_urls", "TEXT")
    return conn

def _ensure_column(conn, table_name, column_name, column_type):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        conn.commit()

def log_pdf(conn, city, feed_name, title, pdf_url, local_path, metadata=None):
    metadata = metadata or {}
    conn.execute("""
        INSERT OR IGNORE INTO agendas
        (
            city, feed_name, meeting_title, meeting_date, pdf_url, local_path, downloaded_at,
            notice_id, notice_url, source_name, government_type, entity, entity_id, public_body, public_body_id,
            county, route_key, mention_key,
            attachment_category, attachment_date_added, event_datetime_raw,
            notice_tags, description_agenda, attachment_count, attachment_urls
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            city,
            feed_name,
            title,
            metadata.get("meeting_date"),
            pdf_url,
            local_path,
            datetime.datetime.now().isoformat(),
            metadata.get("notice_id"),
            metadata.get("notice_url"),
            metadata.get("source_name"),
            metadata.get("government_type"),
            metadata.get("entity"),
            metadata.get("entity_id"),
            metadata.get("public_body"),
            metadata.get("public_body_id"),
            metadata.get("county"),
            metadata.get("route_key"),
            metadata.get("mention_key"),
            metadata.get("attachment_category"),
            metadata.get("attachment_date_added"),
            metadata.get("event_datetime_raw"),
            metadata.get("notice_tags"),
            metadata.get("description_agenda"),
            metadata.get("attachment_count"),
            metadata.get("attachment_urls"),
        ))
    conn.commit()

def load_pmn_sources(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return config.get("sources", [])


def main():
    sources = load_pmn_sources(PMN_CONFIG_PATH)
    conn = get_db_conn()
    existing_notice_ids = set(
        row[0] for row in conn.execute("SELECT notice_id FROM agendas WHERE notice_id IS NOT NULL")
    )

    for source in sources:
        entity = source.get("entity", source.get("name", "Unknown Entity"))
        public_body = source.get("public_body", source.get("name", "Unknown Public Body"))
        base_url = source.get("base_url", "https://www.utah.gov/pmn").rstrip("/")
        public_body_id = str(source.get("public_body_id", "")).strip()
        if not public_body_id:
            print(f"[WARN] Skipping source with missing public_body_id: {source.get('name', '<unnamed>')}")
            continue
        feed_url = f"{base_url}/sitemap/publicbody/{public_body_id}.html"
        storage_dir = source.get("storage_dir")

        print(f"\n=== Processing {entity} / {public_body} ===")
        items = utah_pmn.scrape_feed(
            feed_url,
            base_url,
            entity,
            public_body,
            known_notice_ids=existing_notice_ids,
            storage_dir=storage_dir,
            source_meta=source,
        )
        for record in items:
            log_pdf(
                conn,
                entity,
                public_body,
                record["title"],
                record["pdf_url"],
                record["local_path"],
                metadata=record,
            )
            if record.get("notice_id"):
                existing_notice_ids.add(record["notice_id"])

    conn.close()
    print("\n✅ Download complete.")

if __name__ == "__main__":
    main()
