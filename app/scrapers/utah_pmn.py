import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DATA_DIR = os.getenv("DATA_DIR", "/data")

MEDIA_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".wma",
    ".aac",
    ".m4a",
    ".ogg",
    ".oga",
    ".mp4",
    ".m4v",
    ".mov",
    ".wmv",
    ".avi",
    ".mkv",
}


def scrape_feed(
    feed_url,
    base_url,
    city,
    feed_name,
    known_notice_ids=None,
    storage_dir=None,
    source_meta=None,
    source_seeded=True,
    bootstrap_recency_days=5,
):
    """
    Scrape a Utah PMN public body listing page and download new attachments.

    Expected feed URL format:
    https://www.utah.gov/pmn/sitemap/publicbody/<public_body_id>.html
    """
    if known_notice_ids is None:
        known_notice_ids = set()
    if source_meta is None:
        source_meta = {}

    incoming_dir = storage_dir or os.path.join(DATA_DIR, "incoming", city, feed_name)
    os.makedirs(incoming_dir, exist_ok=True)

    try:
        listing_html = fetch_html(feed_url)
    except Exception as exc:
        print(f"[ERROR] Failed to fetch PMN listing {feed_url}: {exc}")
        return []

    notices = parse_public_body_listing(listing_html, feed_url)
    results = []

    for notice in notices:
        notice_id = notice.get("notice_id")
        if notice_id and notice_id in known_notice_ids:
            continue

        notice_url = notice["notice_url"]
        try:
            detail_html = fetch_html(notice_url)
        except Exception as exc:
            print(f"[WARN] Skipping notice {notice_url}: {exc}")
            continue

        metadata, attachments = parse_notice_detail(detail_html, notice_url, fallback_notice=notice)
        valid_attachments = [
            att for att in attachments
            if att.get("file_url") and not should_skip_attachment(att["file_url"], att.get("category"))
        ]
        primary_attachment = choose_primary_attachment(valid_attachments)

        if primary_attachment:
            local_path = download_attachment(primary_attachment["file_url"], incoming_dir)
            if not local_path:
                continue
            pdf_url = primary_attachment["file_url"]
            attachment_category = primary_attachment.get("category")
            attachment_date_added = primary_attachment.get("date_added")
        else:
            local_path = write_notice_text(incoming_dir, metadata, notice_url, valid_attachments)
            pdf_url = notice_url
            attachment_category = None
            attachment_date_added = None

        meeting_date = normalize_meeting_date(metadata.get("event_start"))
        notification_eligible = int(
            is_notice_notification_eligible(
                meeting_date,
                source_seeded=source_seeded,
                bootstrap_recency_days=bootstrap_recency_days,
            )
        )

        results.append(
            {
                "title": metadata.get("notice_title") or notice.get("title") or "PMN Notice",
                "meeting_date": meeting_date,
                "pdf_url": pdf_url,
                "local_path": local_path,
                "notice_id": notice_id,
                "notice_url": notice_url,
                "source_name": source_meta.get("name"),
                "government_type": source_meta.get("government_type"),
                "entity": source_meta.get("entity", city),
                "entity_id": str(source_meta.get("entity_id") or ""),
                "public_body": source_meta.get("public_body", feed_name),
                "public_body_id": str(source_meta.get("public_body_id") or ""),
                "county": source_meta.get("county"),
                "channel_name": source_meta.get("channel_name"),
                "tag_name": source_meta.get("tag_name"),
                "route_key": source_meta.get("route_key"),
                "mention_key": source_meta.get("mention_key"),
                "tag_key": source_meta.get("tag_key"),
                "attachment_category": attachment_category,
                "attachment_date_added": attachment_date_added,
                "event_datetime_raw": metadata.get("event_start") or notice.get("event_datetime_raw"),
                "notice_tags": metadata.get("notice_tags"),
                "description_agenda": metadata.get("description"),
                "attachment_count": len(valid_attachments),
                "attachment_urls": json.dumps(
                    [att["file_url"] for att in valid_attachments], ensure_ascii=True
                ),
                "notification_eligible": notification_eligible,
            }
        )

    return results


def fetch_html(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.text


def parse_public_body_listing(html, listing_url):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    notices = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        anchor = row.find("a", href=True)
        if not anchor:
            continue
        notice_url = urljoin(listing_url, anchor["href"])
        notices.append(
            {
                "notice_url": notice_url,
                "notice_id": _extract_notice_id(notice_url),
                "title": cells[0].get_text(" ", strip=True),
                "event_datetime_raw": cells[1].get_text(" ", strip=True),
            }
        )
    return notices


def parse_notice_detail(html, detail_url, fallback_notice=None):
    if fallback_notice is None:
        fallback_notice = {}
    soup = BeautifulSoup(html, "html.parser")
    dl_data = parse_definition_lists(soup.find_all("section"))
    attachments = parse_attachments(soup, detail_url)

    metadata = {
        "notice_title": _pick_first(dl_data, ["Notice Title"]) or fallback_notice.get("title") or "",
        "event_start": _pick_first(dl_data, ["Event Start Date & Time"]) or fallback_notice.get("event_datetime_raw"),
        # PMN commonly labels this as "Notice Type(s)" (e.g., "Notice, Bond").
        "notice_tags": _normalize_csvish(
            _pick_first(dl_data, ["Notice Type(s)", "Notice Types", "Notice Tags", "Notice Tag(s)", "Notice Tag"])
        ),
        "description": _pick_first(dl_data, ["Description/Agenda", "Description", "Agenda"]),
    }
    return metadata, attachments


def parse_definition_lists(sections):
    data = {}
    for section in sections:
        for dt_tag in section.find_all("dt"):
            dd_tag = dt_tag.find_next_sibling("dd")
            if not dd_tag:
                continue
            key = dt_tag.get_text(" ", strip=True)
            value = dd_tag.get_text(" ", strip=True)
            if key:
                data[key] = value
    return data


def parse_attachments(soup, page_url):
    header = soup.find(lambda tag: tag.name in {"h2", "h3"} and "Download Attachments" in tag.get_text())
    if not header:
        return []
    table = header.find_next("table")
    if not table:
        return []

    attachments = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        link = row.find("a", href=True)
        file_url = urljoin(page_url, link["href"]) if link else None
        attachments.append(
            {
                "file_name": cells[0].get_text(" ", strip=True),
                "category": cells[1].get_text(" ", strip=True),
                "date_added": cells[2].get_text(" ", strip=True),
                "file_url": file_url,
            }
        )
    return attachments


def choose_primary_attachment(attachments):
    if not attachments:
        return None
    scored = []
    for attachment in attachments:
        url = attachment.get("file_url", "")
        category = (attachment.get("category") or "").lower()
        file_name = (attachment.get("file_name") or "").lower()
        score = 0
        if "agenda" in category or "agenda" in file_name:
            score += 50
        if "packet" in category or "packet" in file_name:
            score += 40
        if "minutes" in category or "minute" in category or "minutes" in file_name:
            score += 30
        if Path(urlparse(url).path).suffix.lower() == ".pdf":
            score += 20
        scored.append((score, attachment))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def should_skip_attachment(file_url, category):
    suffix = Path(urlparse(file_url).path).suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return True
    if category and category.lower() in {"audio", "video"}:
        return True
    return False


def download_attachment(url, dest_dir):
    filename = Path(urlparse(url).path).name or "attachment"
    path = os.path.join(dest_dir, filename)
    if os.path.exists(path):
        return path
    try:
        with requests.get(url, stream=True, timeout=(10, 120)) as response:
            response.raise_for_status()
            with open(path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        handle.write(chunk)
        print(f"Downloaded: {filename}")
        return path
    except Exception as exc:
        print(f"[WARN] Failed to download attachment {url}: {exc}")
        return None


def write_notice_text(dest_dir, metadata, notice_url, attachments):
    notice_id = _extract_notice_id(notice_url) or "notice"
    filename = f"notice_{notice_id}.txt"
    path = os.path.join(dest_dir, filename)
    lines = [
        f"Notice Title: {metadata.get('notice_title') or ''}",
        f"Event Start Date & Time: {metadata.get('event_start') or ''}",
        f"Notice Tags: {metadata.get('notice_tags') or ''}",
        f"Notice URL: {notice_url}",
        "",
        "Description/Agenda:",
        metadata.get("description") or "",
        "",
        "Attachments:",
    ]
    if attachments:
        for attachment in attachments:
            lines.append(f"- {attachment.get('file_name') or ''}: {attachment.get('file_url') or ''}")
    else:
        lines.append("- None")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).strip() + "\n")
    print(f"Saved notice text: {filename}")
    return path


def normalize_meeting_date(value):
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y/%m/%d %I:%M %p", "%B %d, %Y %I:%M %p", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    match = re.search(r"(\d{4})/(\d{2})/(\d{2})", value)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def is_notice_notification_eligible(meeting_date, source_seeded, bootstrap_recency_days, today=None):
    if source_seeded:
        return True
    if not meeting_date:
        return False
    if today is None:
        today = datetime.now().date()
    try:
        meeting_day = datetime.strptime(meeting_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    cutoff = today - timedelta(days=bootstrap_recency_days)
    return meeting_day >= cutoff


def _extract_notice_id(notice_url):
    match = re.search(r"/([0-9]+)\.html$", notice_url)
    if match:
        return match.group(1)
    return Path(urlparse(notice_url).path).stem


def _pick_first(data, candidate_keys):
    lower_to_key = {k.lower(): k for k in data.keys()}
    for key in candidate_keys:
        existing = lower_to_key.get(key.lower())
        if existing:
            return data.get(existing)
    for existing_key, value in data.items():
        existing_lower = existing_key.lower()
        for candidate in candidate_keys:
            if candidate.lower() in existing_lower:
                return value
    return None


def _normalize_csvish(value):
    if not value:
        return value
    parts = [part.strip() for part in re.split(r"\s*,\s*", value) if part.strip()]
    return ", ".join(parts)
