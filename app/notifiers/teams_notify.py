import os
import re

import requests
import yaml


def send_ms_teams_message(notification, webhook_url=None, teams_config_path=None, environ=None):
    """
    Send a message to Microsoft Teams.

    `notification` may be a plain string (legacy mode) or a structured dict.
    """
    if isinstance(notification, str):
        return _send_legacy_message(notification, webhook_url=webhook_url, environ=environ)

    environ = environ or os.environ
    destination = resolve_teams_destination(
        notification,
        webhook_url=webhook_url,
        teams_config_path=teams_config_path,
        environ=environ,
    )
    url = destination.get("webhook_url")
    if not url:
        return destination

    payload = build_adaptive_card_payload(notification, destination)

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as exc:
        print(f"[WARN] Microsoft Teams webhook failed: {exc}")
    return destination


def resolve_teams_destination(notification, webhook_url=None, teams_config_path=None, environ=None):
    environ = environ or os.environ
    teams_config_path = teams_config_path or environ.get("TEAMS_CHANNELS_CONFIG_PATH")
    if not teams_config_path:
        return {
            "webhook_url": webhook_url or environ.get("MS_TEAMS_WEBHOOK_URL") or environ.get("MS_TEAMS_WEBHOOK"),
            "channel_key": None,
            "channel_display_name": None,
            "used_fallback": False,
            "mentions": [],
        }

    try:
        config = load_teams_channels_config(teams_config_path)
    except Exception as exc:
        print(f"[WARN] Could not load Teams channels config {teams_config_path}: {exc}")
        return {
            "webhook_url": webhook_url or environ.get("MS_TEAMS_WEBHOOK_URL") or environ.get("MS_TEAMS_WEBHOOK"),
            "channel_key": None,
            "channel_display_name": None,
            "used_fallback": False,
            "mentions": [],
        }

    channels = config["channels"]
    default_key = config["default_channel"]
    route_key = normalize_key(notification.get("route_key"))
    channel_key = route_key if route_key in channels else default_key
    route_channel = channels.get(channel_key, {})
    used_fallback = channel_key != route_key

    if not channel_is_ready(route_channel, environ):
        channel_key = default_key
        route_channel = channels[default_key]
        used_fallback = True

    if not channel_is_ready(route_channel, environ):
        print(f"[WARN] Default Teams channel '{default_key}' is not active or lacks a webhook")
        resolved_webhook = None
    else:
        resolved_webhook = environ.get(route_channel["webhook_env"])

    mention_groups = config.get("mention_groups", {})
    mentions = resolve_mentions(mention_groups, notification.get("mention_key"))
    return {
        "webhook_url": resolved_webhook,
        "channel_key": channel_key,
        "channel_display_name": route_channel.get("display_name"),
        "used_fallback": used_fallback,
        "mentions": mentions,
    }


def load_teams_channels_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        raise ValueError("Teams config must be a mapping")

    channels = config.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise ValueError("Teams config must define a non-empty channels mapping")

    default_key = normalize_key(config.get("default_channel"))
    if not default_key:
        raise ValueError("Teams config must define default_channel")
    if default_key not in {normalize_key(key) for key in channels.keys()}:
        raise ValueError(f"default_channel '{default_key}' is not present in channels")

    normalized_channels = {}
    for key, value in channels.items():
        if not isinstance(value, dict):
            raise ValueError(f"Channel '{key}' must be a mapping")
        normalized_key = normalize_key(key)
        normalized_channels[normalized_key] = {
            "display_name": value.get("display_name") or str(key),
            "active": bool(value.get("active")),
            "webhook_env": str(value.get("webhook_env") or "").strip(),
        }

    mention_groups = config.get("mention_groups") or {}
    if not isinstance(mention_groups, dict):
        raise ValueError("mention_groups must be a mapping")

    return {
        "default_channel": default_key,
        "channels": normalized_channels,
        "mention_groups": mention_groups,
    }


def build_adaptive_card_payload(notification, destination):
    body = _build_card_body(notification, destination)
    attachment = {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        },
    }

    source_url = notification.get("source_url")
    if source_url:
        attachment["content"]["actions"] = [
            {
                "type": "Action.OpenUrl",
                "title": "Open Source",
                "url": source_url,
            }
        ]

    mention_entities = build_mention_entities(destination.get("mentions", []))
    if mention_entities:
        attachment["content"]["msteams"] = {"entities": mention_entities}

    return {"type": "message", "attachments": [attachment]}


def _build_card_body(notification, destination):
    body = [
        {
            "type": "TextBlock",
            "text": notification.get("title") or "Agenda Summary",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        }
    ]

    mention_block = build_mention_block(destination.get("mentions", []))
    if mention_block:
        body.append(mention_block)

    facts = []
    for key, value in (
        ("City", notification.get("city")),
        ("Feed", notification.get("feed")),
        ("Meeting Date", notification.get("meeting_date") or notification.get("event_datetime_raw")),
        ("Event Date/Time", _secondary_event_value(notification)),
        ("Summarized", notification.get("summarized_at")),
        ("Channel", destination.get("channel_display_name")),
    ):
        if value:
            facts.append({"title": f"{key}:", "value": str(value)})
    if facts:
        body.append({"type": "FactSet", "facts": facts, "spacing": "Small"})

    sections = parse_summary_sections(notification.get("summary_excerpt", ""))
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

    if not sections and notification.get("summary_excerpt"):
        body.append(
            {
                "type": "TextBlock",
                "text": notification["summary_excerpt"],
                "spacing": "Medium",
                "wrap": True,
            }
        )

    return body


def _secondary_event_value(notification):
    meeting_date = str(notification.get("meeting_date") or "").strip()
    event_datetime_raw = str(notification.get("event_datetime_raw") or "").strip()
    if not event_datetime_raw:
        return None
    if meeting_date and meeting_date in event_datetime_raw:
        return event_datetime_raw
    if meeting_date == event_datetime_raw:
        return None
    return event_datetime_raw


def parse_summary_sections(text):
    lines = [line.rstrip() for line in text.splitlines()]
    sections = []
    current_section = None
    current_items = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            continue
        if re.match(r"^\*\*([^*]+):\*\*\s*(.+?)\s*$", line):
            continue
        if line.startswith("## "):
            if current_section:
                sections.append((clean_markdown(current_section), current_items))
            current_section = line[3:].strip()
            current_items = []
            continue
        bullet_match = re.match(r"^[\-\*]\s+(.+)$", line)
        if bullet_match and current_section:
            current_items.append(clean_markdown(bullet_match.group(1)))

    if current_section:
        sections.append((clean_markdown(current_section), current_items))
    return sections


def resolve_mentions(mention_groups, mention_key):
    normalized_key = normalize_key(mention_key)
    if not normalized_key:
        return []

    group = None
    for key, value in mention_groups.items():
        if normalize_key(key) == normalized_key:
            group = value
            break
    if not isinstance(group, dict):
        return []

    if str(group.get("mode") or "users").strip().lower() != "users":
        return []

    mentions = []
    for user in group.get("users", []):
        if not isinstance(user, dict):
            continue
        name = str(user.get("name") or "").strip()
        identifier = str(user.get("entra_object_id") or user.get("upn") or "").strip()
        if not name or not identifier:
            continue
        mentions.append(
            {
                "name": name,
                "id": identifier,
                "text": f"<at>{name}</at>",
            }
        )
    return mentions


def build_mention_block(mentions):
    if not mentions:
        return None
    joined = " ".join(mention["text"] for mention in mentions)
    return {
        "type": "TextBlock",
        "text": joined,
        "wrap": True,
        "spacing": "Small",
    }


def build_mention_entities(mentions):
    entities = []
    for mention in mentions:
        entities.append(
            {
                "type": "mention",
                "text": mention["text"],
                "mentioned": {
                    "id": mention["id"],
                    "name": mention["name"],
                },
            }
        )
    return entities


def channel_is_ready(channel, environ):
    if not channel.get("active"):
        return False
    webhook_env = channel.get("webhook_env")
    if not webhook_env:
        return False
    return bool(str(environ.get(webhook_env) or "").strip())


def normalize_key(value):
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def clean_markdown(value):
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"\*(.*?)\*", r"\1", value)
    return value.strip()


def _send_legacy_message(content, webhook_url=None, environ=None):
    environ = environ or os.environ
    url = webhook_url or environ.get("MS_TEAMS_WEBHOOK_URL") or environ.get("MS_TEAMS_WEBHOOK")
    if not url:
        return None

    text = str(content).strip()
    source_url = _extract_first_url(text)
    card_body = _build_legacy_card_body(text)

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
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as exc:
        print(f"[WARN] Microsoft Teams webhook failed: {exc}")
    return {"webhook_url": url}


def _extract_first_url(text):
    match = re.search(r"https?://[^\s)]+", text)
    if not match:
        return None
    return match.group(0).rstrip(".,;")


def _build_legacy_card_body(text):
    title, metadata, sections = _parse_legacy_summary(text)
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


def _parse_legacy_summary(text):
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
            title = clean_markdown(line[2:].strip())
            continue

        meta_match = re.match(r"^\*\*([^*]+):\*\*\s*(.+?)\s*$", line)
        if meta_match:
            metadata[clean_markdown(meta_match.group(1))] = clean_markdown(meta_match.group(2))
            continue

        if line.startswith("## "):
            if current_section:
                sections.append((current_section, current_items))
            current_section = clean_markdown(line[3:].strip())
            current_items = []
            continue

        bullet_match = re.match(r"^[\-\*]\s+(.+)$", line)
        if bullet_match and current_section:
            current_items.append(clean_markdown(bullet_match.group(1)))
            continue

    if current_section:
        sections.append((current_section, current_items))

    return title, metadata, sections
