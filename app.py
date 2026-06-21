"""
Instagram CTA Auto-Reply Webhook
---------------------------------
Listens for Instagram comment webhooks from Meta. When a comment contains
one of this week's CTA keywords (stored in a Notion page by the weekly
research digest workflow), sends the commenter a private reply with the
link to this week's "All Studies" Notion page.

Environment variables required:
    IG_VERIFY_TOKEN       - any string you choose; must match the value
                            entered in the Meta App webhook configuration
    IG_PAGE_ACCESS_TOKEN  - long-lived Instagram/Page access token with
                            instagram_manage_comments + instagram_business_manage_messages
    NOTION_API_KEY        - Notion internal integration token
    NOTION_CTA_PAGE_ID    - page ID of the "CTA Keywords" Notion page
"""

import os
import json
import requests
from flask import Flask, request, render_template

app = Flask(__name__)

IG_VERIFY_TOKEN = os.environ.get("IG_VERIFY_TOKEN", "")
IG_PAGE_ACCESS_TOKEN = os.environ.get("IG_PAGE_ACCESS_TOKEN", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_CTA_PAGE_ID = os.environ.get("NOTION_CTA_PAGE_ID", "")
NOTION_VERSION = "2022-06-28"

GRAPH_API = "https://graph.instagram.com/v21.0"


def get_cta_data():
    """Read {"keywords": [...], "link": "..."} from the CTA Keywords Notion page."""
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
    }
    try:
        r = requests.get(
            f"https://api.notion.com/v1/blocks/{NOTION_CTA_PAGE_ID}/children",
            headers=headers,
            params={"page_size": 10},
            timeout=15,
        )
        r.raise_for_status()
        for block in r.json().get("results", []):
            if block.get("type") == "code":
                text = "".join(
                    t.get("plain_text", "") for t in block["code"].get("rich_text", [])
                )
                return json.loads(text)
    except Exception as e:
        print(f"[warn] Failed to read CTA data from Notion: {e}")
    return {"keywords": [], "link": ""}

IG_USER_ID = os.environ.get("IG_USER_ID", "")  # your own IG business account ID

def send_private_reply(comment_id, link):
    message = (
        f"Hey! Here's this week's full study list, like I promised: {link}\n\n"
        "Thanks for the comment!"
    )
    r = requests.post(
        f"{GRAPH_API}/{IG_USER_ID}/messages",
        params={"access_token": IG_PAGE_ACCESS_TOKEN},
        json={
            "recipient": {"comment_id": comment_id},
            "message": {"text": message}
        },
        timeout=30,
    )
    if not r.ok:
        print(f"[error] private reply failed for comment {comment_id}: "
              f"{r.status_code} {r.text}")
    else:
        print(f"Sent private reply for comment {comment_id}")

def send_public_reply(comment_id, text="Just sent, check your dms 📩"):
    r = requests.post(
        f"{GRAPH_API}/{comment_id}/replies",
        params={"access_token": IG_PAGE_ACCESS_TOKEN},
        json={"message": text},
        timeout=30,
    )
    if not r.ok:
        print(f"[error] public reply failed for comment {comment_id}: "
              f"{r.status_code} {r.text}")
    else:
        print(f"Posted public reply for comment {comment_id}")

def handle_comment(comment_id, text):
    cta = get_cta_data()
    keywords = [k.lower() for k in cta.get("keywords", [])]
    link = cta.get("link", "")
    if not link or not keywords:
        print("[warn] No active CTA keywords/link configured, skipping.")
        return

    text_lower = text.lower()
    if any(keyword in text_lower for keyword in keywords):
        send_private_reply(comment_id, link)
        send_public_reply(comment_id)


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta calls this once when you configure the webhook subscription."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")
    if mode == "subscribe" and token == IG_VERIFY_TOKEN:
        return challenge, 200
    return "Invalid verify token", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """Meta calls this every time a subscribed event (e.g. a new comment) occurs."""
    data = request.get_json(silent=True) or {}

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            value = change.get("value", {})
            comment_id = value.get("id")
            text = value.get("text", "")
            if comment_id and text:
                try:
                    handle_comment(comment_id, text)
                except Exception as e:
                    print(f"[error] Failed handling comment {comment_id}: {e}")

    # Always return 200 quickly so Meta doesn't retry/disable the subscription
    return "ok", 200


@app.route("/", methods=["GET"])
def health():
    return "CTA webhook is running", 200

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/debug-env", methods=["GET"])
def debug_env():
    """
    TEMPORARY: reports which expected env vars are set (true/false only,
    never the values). Remove this route once things are working.
    """
    return {
        "IG_VERIFY_TOKEN_set": bool(IG_VERIFY_TOKEN),
        "IG_PAGE_ACCESS_TOKEN_set": bool(IG_PAGE_ACCESS_TOKEN),
        "NOTION_API_KEY_set": bool(NOTION_API_KEY),
        "NOTION_CTA_PAGE_ID_set": bool(NOTION_CTA_PAGE_ID),
        "all_env_var_names": sorted(os.environ.keys()),
    }, 200


@app.route("/debug-verify-token", methods=["GET"])
def debug_verify_token():
    """TEMPORARY: shows the exact IG_VERIFY_TOKEN value and length as seen
    by the running app, to debug whitespace/encoding mismatches. Remove
    this route once verification succeeds."""
    return {
        "value": IG_VERIFY_TOKEN,
        "length": len(IG_VERIFY_TOKEN),
        "repr": repr(IG_VERIFY_TOKEN),
    }, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
