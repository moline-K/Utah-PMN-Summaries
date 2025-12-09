import os, re, feedparser, requests
from urllib.parse import urlparse, parse_qs, urlunparse, urljoin

DATA_DIR = os.getenv("DATA_DIR", "/data")

FEED_KEYWORDS = {
    "city council": ["city council"],
    "planning commission": ["planning commission"],
}


def scrape_feed(feed_url, base_url, city, feed_name, known_urls=None):
    """Download PDFs exposed through a Granicus agenda RSS feed."""
    if known_urls is None:
        known_urls = set()

    incoming_dir = os.path.join(DATA_DIR, "incoming", city, feed_name)
    os.makedirs(incoming_dir, exist_ok=True)

    feed = feedparser.parse(feed_url)
    results = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link")
        if not title or not link:
            continue
        if not _matches_feed(title, feed_name):
            continue
        if link in known_urls:
            continue

        path = download_pdf(link, incoming_dir, title)
        if path:
            results.append(
                {
                    "title": title,
                    "pdf_url": link,
                    "local_path": path,
                }
            )
    return results


def _matches_feed(title, feed_name):
    normalized_name = feed_name.lower()
    keywords = FEED_KEYWORDS.get(normalized_name, [normalized_name])
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in keywords)


def download_pdf(url, dest_dir, title):
    filename = _build_filename(title, url)
    path = os.path.join(dest_dir, filename)
    if os.path.exists(path):
        return path
    try:
        content = _fetch_with_sanitized_redirects(url)
    except Exception as exc:
        print(f"[ERROR] Could not download {url}: {exc}")
        return None

    try:
        with open(path, "wb") as fh:
            fh.write(content)
        print(f"Downloaded: {filename}")
        return path
    except OSError as exc:
        print(f"[ERROR] Failed writing {path}: {exc}")
        return None


def _build_filename(title, url):
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "meeting"
    identifier = _extract_identifier(url)
    if identifier:
        return f"{slug}__{identifier}.pdf"
    return f"{slug}.pdf"


def _extract_identifier(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in ("event_id", "clip_id", "meeting_id"):
        if key in params and params[key]:
            return params[key][0]
    match = re.search(r"/(\d+)(?:\.pdf)?$", parsed.path)
    if match:
        return match.group(1)
    return None


def _sanitize_url(url):
    """Rewrite invalid S3 virtual-host URLs to path-style URLs."""
    parsed = urlparse(url)
    host = parsed.netloc
    suffix = ".s3.amazonaws.com"
    if host.endswith(suffix):
        bucket = host[: -len(suffix)]
        if "_" in bucket:
            path = parsed.path
            if not path.startswith(f"/{bucket}/"):
                path = f"/{bucket}{path}"
            parsed = parsed._replace(netloc="s3.amazonaws.com", path=path)
            return urlunparse(parsed)
    return url


def _fetch_with_sanitized_redirects(url, max_redirects=5):
    """Follow redirects manually so we can sanitize S3 URLs before requests hits TLS."""
    session = requests.Session()
    current = url
    for _ in range(max_redirects):
        safe_url = _sanitize_url(current)
        resp = session.get(safe_url, timeout=30, allow_redirects=False)
        if 300 <= resp.status_code < 400 and "Location" in resp.headers:
            location = resp.headers["Location"]
            current = urljoin(resp.url, location)
            continue
        resp.raise_for_status()
        return resp.content
    raise RuntimeError("Too many redirects while fetching Granicus agenda")
