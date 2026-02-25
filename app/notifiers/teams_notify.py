import os
import re

import requests


def send_ms_teams_message(content, webhook_url=None):
    """
    Send a plain-text message to a Microsoft Teams webhook
    (including Power Automate HTTP trigger endpoints).
    """
    url = webhook_url or os.getenv("MS_TEAMS_WEBHOOK_URL") or os.getenv("MS_TEAMS_WEBHOOK")
    if not url:
        return

    text = str(content).strip()
    source_url = _extract_first_url(text)
    card_body = _build_card_body(text)

    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": card_body,
                },
            }
        ],
    }
    if source_url:
        payload["attachments"][0]["content"]["actions"] = [
            {
                "type": "Action.OpenUrl",
                "title": "Open Source",
                "url": source_url,
            }
        ]

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[WARN] Microsoft Teams webhook failed: {exc}")


def _extract_first_url(text):
    match = re.search(r"https?://[^\s)]+", text)
    if not match:
        return None
    return match.group(0).rstrip(".,;")


def _build_card_body(text):
    title, metadata, sections = _parse_summary(text)
    body = [
        {
            "type": "TextBlock",
            "text": title or "Agenda Summary",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        }
    ]

    facts = []
    for key in ("City", "Feed", "Meeting Date", "Summarized"):
        value = metadata.get(key)
        if value:
            facts.append({"title": f"{key}:", "value": value})
    if facts:
        body.append({"type": "FactSet", "facts": facts, "spacing": "Small"})

    for section_title, items in sections:
        body.append(
            {
                "type": "TextBlock",
                "text": section_title,
                "weight": "Bolder",
                "color": "Accent",
                "spacing": "Medium",
                "wrap": True,
            }
        )
        if items:
            for item in items:
                body.append(
                    {
                        "type": "TextBlock",
                        "text": f"• {item}",
                        "spacing": "Small",
                        "wrap": True,
                    }
                )
        else:
            body.append(
                {
                    "type": "TextBlock",
                    "text": "No items.",
                    "spacing": "Small",
                    "wrap": True,
                }
            )

    return body


def _parse_summary(text):
    lines = [line.rstrip() for line in text.splitlines()]
    title = None
    metadata = {}
    sections = []
    current_section = None
    current_items = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# ") and not title:
            title = _clean_markdown(line[2:].strip())
            continue

        meta_match = re.match(r"^\*\*([^*]+):\*\*\s*(.+?)\s*$", line)
        if meta_match:
            metadata[_clean_markdown(meta_match.group(1))] = _clean_markdown(meta_match.group(2))
            continue

        if line.startswith("## "):
            if current_section:
                sections.append((current_section, current_items))
            current_section = _clean_markdown(line[3:].strip())
            current_items = []
            continue

        bullet_match = re.match(r"^[\-\*]\s+(.+)$", line)
        if bullet_match and current_section:
            current_items.append(_clean_markdown(bullet_match.group(1)))
            continue

    if current_section:
        sections.append((current_section, current_items))

    return title, metadata, sections


def _clean_markdown(value):
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"\*(.*?)\*", r"\1", value)
    return value.strip()
