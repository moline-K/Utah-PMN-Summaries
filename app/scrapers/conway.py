import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, urlparse, urljoin

import requests
from bs4 import BeautifulSoup

DATA_DIR = os.getenv("DATA_DIR", "/data")
PDF_PROXY_BASE = os.getenv("PDF_READER_PROXY")
USER_AGENT = os.getenv("CONWAY_USER_AGENT", "agenda-downloader/1.0")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def scrape_feed(feed_url, base_url, city, feed_name, known_urls=None):
    if known_urls is None:
        known_urls = set()

    incoming_dir = os.path.join(DATA_DIR, "incoming", city, feed_name)
    os.makedirs(incoming_dir, exist_ok=True)

    year = _extract_year(feed_url)
    board_label = _infer_board_label(feed_url, feed_name)

    try:
        html = _fetch_page(feed_url)
    except Exception as exc:
        print(f"[ERROR] Failed to fetch {feed_url}: {exc}")
        return []

    table = _locate_board_table(html, board_label)
    if not table:
        print(f"[WARN] {city}/{feed_name}: no table found for '{board_label}'")
        return []

    meetings = _parse_meeting_rows(table, board_label, base_url, year)
    results = []

    for meeting in meetings:
        date_label = meeting["date"].strftime("%Y-%m-%d")
        title_prefix = f"{feed_name} - {date_label}"
        for document in meeting["documents"]:
            doc_type = document["type"]
            if doc_type not in {"agenda", "summary"}:
                continue
            pdf_url = document["url"]
            if pdf_url in known_urls:
                continue
            local_path = download_pdf(pdf_url, incoming_dir, meeting["date"], doc_type)
            if not local_path:
                continue
            results.append(
                {
                    "title": f"{title_prefix} ({doc_type.title()})",
                    "pdf_url": pdf_url,
                    "local_path": local_path,
                }
            )
    return results


def _fetch_page(url: str) -> str:
    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def _infer_board_label(feed_url: str, fallback: str) -> str:
    parsed = urlparse(feed_url)
    params = parse_qs(parsed.query)
    tab = params.get("tab", [None])[0]
    if tab:
        tab = tab.replace("-", " ")
        return tab.title()
    return fallback


def _extract_year(url: str) -> int:
    match = re.search(r"/meeting-archives/(\d{4})/", url)
    if match:
        return int(match.group(1))
    return datetime.now().year


def _locate_board_table(html: str, board_label: str):
    soup = BeautifulSoup(html, "html.parser")
    normalized_target = _normalize(board_label)
    label_map = {}
    for tab_button in soup.select("[role='tab'][id]"):
        label_map[tab_button["id"]] = _normalize(tab_button.get_text(" ", strip=True))

    for panel in soup.select("div[role='tabpanel']"):
        button_id = panel.get("aria-labelledby")
        if not button_id:
            continue
        label = label_map.get(button_id)
        if label == normalized_target:
            table = panel.find("table")
            if table:
                return table

    for node in soup.find_all(["h2", "h3", "span", "strong"]):
        if _normalize(node.get_text(" ", strip=True)) == normalized_target:
            table = node.find_next("table")
            if table:
                return table

    tables = soup.find_all("table")
    if len(tables) == 1:
        return tables[0]
    return None


def _parse_meeting_rows(table, board_label: str, base_url: str, year: int):
    header_cells = table.find_all("th")
    documents_idx = _find_column_index(header_cells, "document")
    if documents_idx is None:
        print(f"[WARN] {board_label}: Missing documents column")
        return []

    meetings = []
    body = table.find("tbody") or table
    for row in body.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) <= documents_idx:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        meeting_date = _parse_date(date_text, year)
        if not meeting_date or meeting_date.year != year:
            continue
        doc_cell = cells[documents_idx]
        docs = _extract_documents(doc_cell, base_url)
        if not docs:
            continue
        meetings.append({"date": meeting_date, "documents": docs})
    return meetings


def _find_column_index(headers, keyword: str) -> Optional[int]:
    keyword = keyword.lower()
    for idx, header in enumerate(headers):
        text = header.get_text(" ", strip=True).lower()
        if keyword in text:
            return idx
    return None


def _parse_date(text: str, default_year: int) -> Optional[datetime]:
    text = text.strip()
    if not text:
        return None
    text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text)
    formats = ["%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y"]
    if not re.search(r"\d{4}", text):
        text = f"{text}, {default_year}"
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _extract_documents(cell, base_url: str) -> List[Dict[str, str]]:
    docs = []
    for link in cell.find_all("a", href=True):
        label = link.get_text(" ", strip=True).lower()
        doc_type = None
        if "agenda" in label:
            doc_type = "agenda"
        elif "summary" in label:
            doc_type = "summary"
        elif "minute" in label:
            doc_type = "minutes"
        else:
            continue
        href = urljoin(base_url, link["href"])
        docs.append({"type": doc_type, "url": href})
    return docs


def download_pdf(pdf_url: str, dest_dir: str, meeting_date: datetime, doc_type: str):
    filename = _build_filename(pdf_url, meeting_date, doc_type)
    path = os.path.join(dest_dir, filename)
    if os.path.exists(path):
        return path
    try:
        content = _fetch_pdf_content(pdf_url)
    except Exception as exc:
        print(f"[ERROR] Failed to download {pdf_url}: {exc}")
        return None
    try:
        with open(path, "wb") as fh:
            fh.write(content)
    except OSError as exc:
        print(f"[ERROR] Could not write {path}: {exc}")
        return None
    print(f"Downloaded: {filename}")
    return path


def _fetch_pdf_content(url: str) -> bytes:
    resp = SESSION.get(url, timeout=45)
    if resp.status_code == 403 and PDF_PROXY_BASE:
        proxied = f"{PDF_PROXY_BASE}?url={quote_plus(url)}"
        resp = SESSION.get(proxied, timeout=45)
    resp.raise_for_status()
    return resp.content


def _build_filename(pdf_url: str, meeting_date: datetime, doc_type: str) -> str:
    date_part = meeting_date.strftime("%Y-%m-%d")
    doc_part = re.sub(r"[^a-z0-9]+", "-", doc_type.lower()).strip("-") or "document"
    tail = Path(urlparse(pdf_url).path).name or "meeting.pdf"
    return f"{date_part}__{doc_part}__{tail}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())
