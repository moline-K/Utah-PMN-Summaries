import os

import fitz
from openai import OpenAI
from .base_summarizer import BaseSummarizer
from notifiers.discord_notify import send_discord_message
from notifiers.teams_notify import send_ms_teams_message

DEFAULT_PROMPT_TEMPLATE = """
You are a civil engineering and planning analyst. You want to be able to inform friends and family about what is going on in the city.
Read the following city council meeting agenda and produce a concise, structured Markdown summary of only the items that have engineering, planning, zoning, infrastructure, or capital project relevance.

Focus on:
- Zoning or land-use changes (include parcel/street info)
- Subdivisions, site plans, or developments
- Road, traffic, or transportation projects
- Water, sewer, storm drain, or utility upgrades
- Engineering studies, capital projects, grants, or contracts
- Any fiscal or policy actions that affect construction or infrastructure
Exclude:
- Ceremonial items, proclamations, recognitions, or awards
- Minutes approval, consent agendas, or administrative procedures
- Public comments unrelated to engineering

Format the output like this:

## Key Engineering Actions
- [One-sentence bullet per action or motion, include project/location]
## Notable Locations or Projects
- [Street names, subdivisions, or landmarks referenced]
## Funding / Contracts
- [Any bids, grants, or budgets related to infrastructure]

Keep it factual, concise, and neutral.
Do not include meeting logistics, pledges, or adjournment.

Now summarize the following agenda text:

{{AGENDA_TEXT}}
"""


class OpenaiSummarizer(BaseSummarizer):
    def __init__(self, *args, discord_webhook=None, teams_webhook=None, **kwargs):
        super().__init__(*args, discord_webhook=discord_webhook, teams_webhook=teams_webhook, **kwargs)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.prompt_template = self._load_prompt_template()
        #self.n8n_webhook = os.getenv("N8N_WEBHOOK_URL")

    def extract_text(self, pdf_path):
        if not self._looks_like_pdf(pdf_path):
            print(f"[WARN] {pdf_path} does not look like a PDF; using plain-text fallback")
            return self._read_plain_text(pdf_path)

        try:
            text_chunks = []
            with fitz.open(pdf_path) as doc:
                for page in doc:
                    text_chunks.append(page.get_text())
            return "".join(text_chunks).strip()
        except Exception as exc:
            print(f"[WARN] Failed to open {pdf_path} as PDF ({exc}); using plain-text fallback")
            return self._read_plain_text(pdf_path)

    def summarize_text(self, text, title):
        prompt = self.prompt_template.replace("{{AGENDA_TEXT}}", text[:80000]).replace("{{TITLE}}", title or "")
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You summarize civic meeting agendas concisely."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    def notify(self, notice, doc_type, summary_path, summarized_at):
        excerpt = self._read_summary_excerpt(summary_path)
        #self._notify_n8n(title, excerpt)
        self._notify_discord(notice, doc_type, excerpt)
        self._notify_teams(notice, doc_type, excerpt, summarized_at)

    def _read_summary_excerpt(self, summary_path, limit=1500):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            return ""
        text = self._strip_front_matter(text)
        if len(text) > limit:
            return text[:limit].rstrip() + "..."
        return text

    def _strip_front_matter(self, text):
        """Remove YAML-style metadata from the top of the summary."""
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return text
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                return "\n".join(lines[idx + 1:]).lstrip("\n")
        return text

    def _looks_like_pdf(self, path, sniff_bytes=4):
        try:
            with open(path, "rb") as fh:
                header = fh.read(sniff_bytes)
            return header.startswith(b"%PDF")
        except Exception as exc:
            print(f"[WARN] Unable to read header from {path}: {exc}")
            return False

    def _read_plain_text(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                return fh.read().strip()
        except Exception as exc:
            print(f"[ERROR] Unable to read fallback text from {path}: {exc}")
            return ""

    #def _notify_n8n(self, title, excerpt):
    #    if not self.n8n_webhook:
    #        return
    #    try:
    #        response = requests.post(
    #            self.n8n_webhook,
    #            json={"title": title, "summary": excerpt},
    #            timeout=10,
    #        )
    #        response.raise_for_status()
    #    except Exception as e:
    #        print(f"[WARN] webhook failed: {e}")

    def _notify_discord(self, notice, doc_type, excerpt):
        print(f"[DEBUG] _notify_discord called")
        print(f"[DEBUG] self.discord_webhook = {self.discord_webhook}")
        if not self.discord_webhook:
            print("[DEBUG] No Discord webhook configured")
            return
        print("[DEBUG] Building message...")
        heading = f"**{notice['city']} - {notice['feed_name']} ({doc_type})**"
        body_lines = [heading]
        if notice.get("meeting_title"):
            body_lines.append(f"*{notice['meeting_title']}*")
        if notice.get("meeting_date"):
            body_lines.append(f"Meeting Date: {notice['meeting_date']}")
        elif notice.get("event_datetime_raw"):
            body_lines.append(f"Event Date/Time: {notice['event_datetime_raw']}")
        if excerpt:
            body_lines.append("")
            body_lines.append(excerpt)
        body_lines.append("")
        body_lines.append(f"Original PDF: {notice['pdf_url']}")
        content = "\n".join(body_lines)
        if len(content) > 1900:
            content = content[:1900] + "..."
        send_discord_message(self.discord_webhook, content)

    def _notify_teams(self, notice, doc_type, excerpt, summarized_at):
        print(f"[DEBUG] _notify_teams called")
        print(f"[DEBUG] self.teams_webhook = {self.teams_webhook}")
        payload = {
            "title": notice.get("meeting_title") or f"{notice['city']} - {notice['feed_name']}",
            "city": notice.get("city"),
            "feed": notice.get("feed_name"),
            "doc_type": doc_type,
            "source_url": notice.get("pdf_url"),
            "summary_excerpt": excerpt,
            "meeting_date": notice.get("meeting_date"),
            "event_datetime_raw": notice.get("event_datetime_raw"),
            "summarized_at": summarized_at.isoformat(timespec="minutes"),
            "entity": notice.get("entity"),
            "entity_id": notice.get("entity_id"),
            "public_body": notice.get("public_body"),
            "public_body_id": notice.get("public_body_id"),
            "county": notice.get("county"),
            "route_key": notice.get("route_key"),
            "mention_key": notice.get("mention_key"),
            "notice_id": notice.get("notice_id"),
            "notice_url": notice.get("notice_url"),
            "notice_tags": notice.get("notice_tags"),
        }
        send_ms_teams_message(payload, webhook_url=self.teams_webhook)

    def _load_prompt_template(self):
        path = os.getenv("PROMPT_TEMPLATE_PATH")
        if not path:
            return DEFAULT_PROMPT_TEMPLATE.strip()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = f.read().strip()
            if not data:
                return DEFAULT_PROMPT_TEMPLATE.strip()
            return data
        except Exception as exc:
            print(f"[WARN] Could not load PROMPT_TEMPLATE_PATH {path}: {exc}")
            return DEFAULT_PROMPT_TEMPLATE.strip()
