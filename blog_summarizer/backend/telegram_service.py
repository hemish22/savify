"""
Telegram Bot Service — URL extraction, message formatting, and Telegram API helpers.
"""

import os
import re
import asyncio

import httpx
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Regex to extract URLs from message text
URL_PATTERN = re.compile(
    r'https?://[^\s<>"\')\]]+',
    re.IGNORECASE
)


def extract_url_from_text(text: str) -> str | None:
    """Extract the first URL from a Telegram message."""
    if not text:
        return None
    match = URL_PATTERN.search(text)
    return match.group(0).rstrip(".,;:!?)") if match else None


def format_summary_for_telegram(result: dict) -> str:
    """Format a summary dict into a clean Telegram message with emoji."""
    title = result.get("title", "Untitled")
    difficulty = result.get("difficulty", "Unknown")
    category = result.get("category", "General")
    summary = result.get("summary", "")
    key_points = result.get("key_points", [])
    takeaway = result.get("takeaway", "")
    source_type = result.get("source_type", "blog")
    url = result.get("original_url", "")

    source_emoji = {"youtube": "🎬", "instagram": "📸", "blog": "📝"}.get(source_type, "📝")
    diff_emoji = {"Beginner": "🟢", "Intermediate": "🟡", "Advanced": "🔴"}.get(difficulty, "⚪")

    points_text = "\n".join(f"  • {p}" for p in key_points[:5]) if key_points else "  • No key points available"

    msg = (
        f"{source_emoji} *{_escape_md(title)}*\n"
        f"{diff_emoji} {difficulty} · {category}\n"
        f"{'─' * 28}\n\n"
        f"📋 *Summary*\n"
        f"{_escape_md(summary)}\n\n"
        f"🔑 *Key Points*\n"
        f"{_escape_md(points_text)}\n\n"
        f"💡 *Takeaway*\n"
        f"{_escape_md(takeaway)}\n\n"
        f"{'─' * 28}\n"
        f"🔗 [View Original]({url})\n"
        f"✅ _Saved to your Knowledge Base_"
    )
    return msg


def _escape_md(text: str) -> str:
    """Escape special Markdown V2 characters for Telegram."""
    if not text:
        return ""
    # Characters that must be escaped in Telegram MarkdownV2
    escape_chars = r'_[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


async def send_telegram_message(chat_id: int, text: str, parse_mode: str = "MarkdownV2"):
    """Send a message back to the user via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN not set. Cannot send message.")
        return

    async with httpx.AsyncClient(timeout=30) as client:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = await client.post(f"{TELEGRAM_API_BASE}/sendMessage", json=payload)
            if resp.status_code != 200:
                # Fallback: send as plain text if markdown fails
                payload["parse_mode"] = ""
                payload["text"] = text.replace("*", "").replace("_", "").replace("\\", "")
                await client.post(f"{TELEGRAM_API_BASE}/sendMessage", json=payload)
        except Exception as e:
            print(f"❌ Telegram send error: {e}")


async def send_typing_action(chat_id: int):
    """Show 'typing...' indicator in Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                f"{TELEGRAM_API_BASE}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
        except Exception:
            pass


async def register_webhook(webhook_url: str) -> dict:
    """Register a webhook URL with Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not set"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{TELEGRAM_API_BASE}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message"]}
        )
        return resp.json()


async def delete_webhook() -> dict:
    """Remove any registered webhook so getUpdates polling can be used."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not set"}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{TELEGRAM_API_BASE}/deleteWebhook")
        return resp.json()


async def poll_updates(handle_message):
    """
    Long-poll Telegram getUpdates and dispatch each message to handle_message.
    Used for local development where no public webhook URL exists.
    Runs forever; cancel the task to stop.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN not set. Polling disabled.")
        return

    offset = 0
    print("📡 Telegram polling started (local mode)")
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            try:
                resp = await client.get(
                    f"{TELEGRAM_API_BASE}/getUpdates",
                    params={"offset": offset, "timeout": 50, "allowed_updates": '["message"]'},
                )
                data = resp.json()
                if not data.get("ok"):
                    # 409 = webhook still registered; other errors — back off and retry
                    print(f"⚠️ getUpdates error: {data.get('description')}")
                    await asyncio.sleep(5)
                    continue
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if message:
                        # Fire-and-forget so a slow summary doesn't block polling
                        asyncio.create_task(handle_message(message))
            except asyncio.CancelledError:
                print("📡 Telegram polling stopped")
                raise
            except Exception as e:
                print(f"⚠️ Telegram polling error: {e}")
                await asyncio.sleep(5)


async def get_bot_info() -> dict:
    """Get info about the bot (useful for verification)."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not set"}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{TELEGRAM_API_BASE}/getMe")
        return resp.json()
