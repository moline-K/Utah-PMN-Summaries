import os, re, feedparser, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path

DATA_DIR = os.getenv("DATA_DIR", "/data")

def scrape_feed(feed_url, base_url, city, feed_name, known_urls=None):
    """Parse an RSS feed and download linked PDFs."""
    if known_urls is None:
        known_urls = set()
    incoming_dir = os.path.join(DATA_DIR, "incoming", city, feed_name)
    os.makedirs(incoming_dir, exist_ok=True)
    results = []

    feed = feedparser.parse(feed_url)
    for entry in feed.entries:
        if "AgendaCenter" not in entry.link:
            continue
        for pdf_url in extract_pdfs_from_page(entry.link, base_url):
            if pdf_url in known_urls:
                continue
            path = download_pdf(pdf_url, incoming_dir)
            if path:
                results.append({
                    "title": entry.title,
                    "pdf_url": pdf_url,
                    "local_path": path
                })
    return results

def extract_pdfs_from_page(page_url, base_url):
    try:
        res = requests.get(page_url, timeout=15)
        res.raise_for_status()
    except Exception as e:
        print(f"[ERROR] {page_url}: {e}")
        return []
    soup = BeautifulSoup(res.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        if re.search(r"/AgendaCenter/ViewFile/(Agenda|Minutes)/", a["href"], re.I):
            links.append(urljoin(base_url, a["href"]))
    return list(set(links))

def download_pdf(url, dest_dir):
    filename = os.path.basename(url)
    match = re.search(r"/ViewFile/([^/]+)/([^/?]+)", url)
    if match:
        doc_type, base_name = match.groups()
        filename = f"{doc_type.lower()}_{base_name}"
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    path = os.path.join(dest_dir, filename)
    if os.path.exists(path):
        return path
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"Downloaded: {filename}")
        return path
    except Exception as e:
        print(f"[ERROR] Could not download {url}: {e}")
        return None
