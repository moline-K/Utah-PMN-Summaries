import requests

def send_discord_message(webhook_url, content):
    if not webhook_url:
        return
    try:
        response = requests.post(
            webhook_url,
            json={"content": content},
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[WARN] Discord webhook failed: {exc}")
