"""
FastAPI application for Blog Summarizer.
Supports Blog, YouTube, and Instagram URL summarization with real-time progress.
Includes Telegram Bot webhook for mobile ingestion.
"""

import os
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from models import SummarizeRequest, SummaryResponse
from database import init_db, save_summary, get_all_summaries, delete_summary, update_favorite, update_summary_text
from scraper import scrape_article
from llm_service import summarize_text, summarize_youtube
from youtube_service import is_youtube_url, fetch_transcript, extract_video_id, _fetch_via_api
from instagram_service import is_instagram_url, fetch_instagram_transcript
from audio_service import download_audio, cleanup_audio
from whisper_service import transcribe_audio
from transcript_cleaner import clean_transcript
from telegram_service import (
    extract_url_from_text, format_summary_for_telegram,
    send_telegram_message, send_typing_action,
    register_webhook, delete_webhook, poll_updates, get_bot_info,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize database on startup.
    Telegram: webhook mode on Render (public URL), getUpdates polling locally.
    """
    init_db()
    print("✅ Database initialized")

    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    polling_task = None

    if render_url and telegram_token:
        # Render: RENDER_EXTERNAL_URL is set automatically — use webhook
        webhook_url = f"{render_url}/telegram-webhook"
        try:
            result = await register_webhook(webhook_url)
            print(f"✅ Telegram webhook auto-registered: {webhook_url}")
            print(f"   Result: {result}")
        except Exception as e:
            print(f"⚠️ Telegram webhook auto-registration failed: {e}")
    elif telegram_token:
        # Local: no public URL — remove any stale webhook and long-poll instead
        try:
            await delete_webhook()
            polling_task = asyncio.create_task(poll_updates(_handle_telegram_message))
        except Exception as e:
            print(f"⚠️ Telegram polling setup failed: {e}")

    yield

    if polling_task:
        polling_task.cancel()


app = FastAPI(
    title="Blog Summarizer",
    description="Paste a blog, YouTube, or Instagram URL — get a structured AI summary with real-time progress.",
    version="1.3.0",
    lifespan=lifespan,
)

# CORS — allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ──────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────

@app.get("/")
async def serve_homepage():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(os.path.join(FRONTEND_DIR, "dashboard.html"))


# ──────────────────────────────────────────────
# SSE Helpers
# ──────────────────────────────────────────────

def sse_event(data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"data: {json.dumps(data)}\n\n"


# ──────────────────────────────────────────────
# Streaming Summarize Endpoint (Real-time Progress)
# ──────────────────────────────────────────────

@app.post("/summarize-stream")
async def summarize_stream(request: SummarizeRequest):
    """
    Stream real-time progress events during summarization.
    Returns Server-Sent Events (SSE) with progress updates.
    """
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required.")

    async def event_generator():
        try:
            # ── Route: Instagram ──
            if is_instagram_url(url):
                yield sse_event({"step": "detect", "status": "done", "message": "📸 Instagram Reel detected"})

                yield sse_event({"step": "download", "status": "active", "message": "📥 Downloading reel audio..."})
                audio_path = await asyncio.to_thread(download_audio, url)
                yield sse_event({"step": "download", "status": "done", "message": "✅ Audio downloaded"})

                yield sse_event({"step": "transcribe", "status": "active", "message": "🎙️ Transcribing with Whisper AI..."})
                whisper_result = await asyncio.to_thread(transcribe_audio, audio_path)
                cleanup_audio(audio_path)
                yield sse_event({"step": "transcribe", "status": "done", "message": f"✅ Transcribed ({whisper_result['language']})"})

                yield sse_event({"step": "clean", "status": "active", "message": "🧹 Cleaning transcript..."})
                cleaned_text = clean_transcript(whisper_result["text"])
                yield sse_event({"step": "clean", "status": "done", "message": "✅ Transcript cleaned"})

                if not cleaned_text or len(cleaned_text) < 20:
                    yield sse_event({"step": "error", "status": "error", "message": "❌ No meaningful speech found in this reel."})
                    return

                # Truncate
                if len(cleaned_text) > 30000:
                    cleaned_text = cleaned_text[:30000] + "... [truncated]"

                yield sse_event({"step": "summarize", "status": "active", "message": "🤖 Generating AI summary..."})
                summary_data = await asyncio.to_thread(summarize_youtube, cleaned_text)
                yield sse_event({"step": "summarize", "status": "done", "message": "✅ Summary generated"})

                result = {
                    "title": summary_data["title"],
                    "domain": "instagram.com",
                    "difficulty": summary_data["difficulty"],
                    "summary": summary_data["summary"],
                    "key_points": summary_data["key_points"],
                    "takeaway": summary_data["takeaway"],
                    "original_url": url,
                    "source_type": "instagram",
                    "tools_mentioned": summary_data.get("tools_mentioned", []),
                }

            # ── Route: YouTube ──
            elif is_youtube_url(url):
                video_id = extract_video_id(url)
                yield sse_event({"step": "detect", "status": "done", "message": "🎬 YouTube video detected"})

                yield sse_event({"step": "transcript", "status": "active", "message": "📝 Fetching transcript..."})
                api_result = await asyncio.to_thread(_fetch_via_api, video_id)

                if api_result is not None:
                    # Fast path: API transcript available
                    text = api_result["text"]
                    yield sse_event({"step": "transcript", "status": "done", "message": "✅ Transcript fetched via API"})
                else:
                    # Slow path: Whisper fallback
                    yield sse_event({"step": "transcript", "status": "done", "message": "⚠️ No transcript available — using Whisper"})

                    yield sse_event({"step": "download", "status": "active", "message": "📥 Downloading video audio..."})
                    audio_path = await asyncio.to_thread(download_audio, url)
                    yield sse_event({"step": "download", "status": "done", "message": "✅ Audio downloaded"})

                    yield sse_event({"step": "transcribe", "status": "active", "message": "🎙️ Transcribing with Whisper AI..."})
                    whisper_result = await asyncio.to_thread(transcribe_audio, audio_path)
                    cleanup_audio(audio_path)
                    yield sse_event({"step": "transcribe", "status": "done", "message": f"✅ Transcribed ({whisper_result['language']})"})

                    yield sse_event({"step": "clean", "status": "active", "message": "🧹 Cleaning transcript..."})
                    text = clean_transcript(whisper_result["text"])
                    yield sse_event({"step": "clean", "status": "done", "message": "✅ Transcript cleaned"})

                # Truncate
                if len(text) > 30000:
                    text = text[:30000] + "... [truncated]"

                yield sse_event({"step": "summarize", "status": "active", "message": "🤖 Generating AI summary..."})
                summary_data = await asyncio.to_thread(summarize_youtube, text)
                yield sse_event({"step": "summarize", "status": "done", "message": "✅ Summary generated"})

                result = {
                    "title": summary_data["title"],
                    "domain": "youtube.com",
                    "difficulty": summary_data["difficulty"],
                    "summary": summary_data["summary"],
                    "key_points": summary_data["key_points"],
                    "takeaway": summary_data["takeaway"],
                    "original_url": url,
                    "source_type": "youtube",
                    "tools_mentioned": summary_data.get("tools_mentioned", []),
                }

            # ── Route: Blog ──
            else:
                yield sse_event({"step": "detect", "status": "done", "message": "📝 Blog article detected"})

                yield sse_event({"step": "scrape", "status": "active", "message": "🌐 Scraping article content..."})
                article = await asyncio.to_thread(scrape_article, url)
                yield sse_event({"step": "scrape", "status": "done", "message": f"✅ Scraped from {article['domain']}"})

                yield sse_event({"step": "summarize", "status": "active", "message": "🤖 Generating AI summary..."})
                summary_data = await asyncio.to_thread(summarize_text, article["text"])
                yield sse_event({"step": "summarize", "status": "done", "message": "✅ Summary generated"})

                result = {
                    "title": summary_data["title"],
                    "domain": article["domain"],
                    "difficulty": summary_data["difficulty"],
                    "summary": summary_data["summary"],
                    "key_points": summary_data["key_points"],
                    "takeaway": summary_data["takeaway"],
                    "original_url": url,
                    "source_type": "blog",
                    "tools_mentioned": [],
                }

            # ── Save to DB ──
            yield sse_event({"step": "save", "status": "active", "message": "💾 Saving to database..."})
            try:
                row_id = save_summary(result)
                result["id"] = row_id
            except Exception as e:
                if "UNIQUE" in str(e):
                    result["id"] = None
                else:
                    yield sse_event({"step": "error", "status": "error", "message": f"⚠️ Save failed: {str(e)}"})
            yield sse_event({"step": "save", "status": "done", "message": "✅ Saved to database"})

            # ── Final result ──
            yield sse_event({"step": "complete", "status": "done", "message": "🎉 All done!", "result": result})

        except Exception as e:
            yield sse_event({"step": "error", "status": "error", "message": f"❌ {str(e)}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────
# Legacy Non-Streaming Endpoints
# ──────────────────────────────────────────────

@app.post("/summarize", response_model=SummaryResponse)
async def summarize_url(request: SummarizeRequest):
    """Non-streaming summarize endpoint (kept for backward compatibility)."""
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required.")

    if is_instagram_url(url):
        try:
            transcript_data = await asyncio.to_thread(fetch_instagram_transcript, url)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        summary_data = await asyncio.to_thread(summarize_youtube, transcript_data["text"])
        result = {
            "title": summary_data["title"], "domain": transcript_data["domain"],
            "difficulty": summary_data["difficulty"], "summary": summary_data["summary"],
            "key_points": summary_data["key_points"], "takeaway": summary_data["takeaway"],
            "original_url": url, "source_type": "instagram",
            "tools_mentioned": summary_data.get("tools_mentioned", []),
        }
    elif is_youtube_url(url):
        try:
            transcript_data = await asyncio.to_thread(fetch_transcript, url)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        summary_data = await asyncio.to_thread(summarize_youtube, transcript_data["text"])
        result = {
            "title": summary_data["title"], "domain": transcript_data["domain"],
            "difficulty": summary_data["difficulty"], "summary": summary_data["summary"],
            "key_points": summary_data["key_points"], "takeaway": summary_data["takeaway"],
            "original_url": url, "source_type": "youtube",
            "tools_mentioned": summary_data.get("tools_mentioned", []),
        }
    else:
        try:
            article = await asyncio.to_thread(scrape_article, url)
        except (ValueError, TimeoutError, ConnectionError) as e:
            raise HTTPException(status_code=502, detail=str(e))
        summary_data = await asyncio.to_thread(summarize_text, article["text"])
        result = {
            "title": summary_data["title"], "domain": article["domain"],
            "difficulty": summary_data["difficulty"], "summary": summary_data["summary"],
            "key_points": summary_data["key_points"], "takeaway": summary_data["takeaway"],
            "original_url": url, "source_type": "blog", "tools_mentioned": [],
        }

    try:
        row_id = save_summary(result)
        result["id"] = row_id
    except Exception:
        result["id"] = None

    return result


@app.get("/summaries")
async def list_summaries():
    """Return all saved summaries."""
    try:
        summaries = get_all_summaries()
        return {"summaries": summaries, "count": len(summaries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve summaries: {str(e)}")


@app.delete("/summaries/{summary_id}")
async def remove_summary(summary_id: int):
    """Delete a summary by ID."""
    deleted = delete_summary(summary_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Summary not found.")
    return {"message": "Summary deleted.", "id": summary_id}


@app.post("/summaries/{summary_id}/favorite")
async def toggle_summary_favorite(summary_id: int, request: Request):
    """Toggle the favorite status of a summary."""
    data = await request.json()
    is_favorite = data.get("is_favorite", False)
    updated = update_favorite(summary_id, is_favorite)
    if not updated:
        raise HTTPException(status_code=404, detail="Summary not found.")
    return {"message": "Favorite status updated.", "is_favorite": is_favorite}


@app.put("/summaries/{summary_id}/edit")
async def edit_summary_content(summary_id: int, request: Request):
    """Update the summary text for a specific entry."""
    data = await request.json()
    new_text = data.get("summary", "").strip()
    if not new_text:
        raise HTTPException(status_code=400, detail="Summary text cannot be empty.")
    
    updated = update_summary_text(summary_id, new_text)
    if not updated:
        raise HTTPException(status_code=404, detail="Summary not found.")
    return {"message": "Summary updated successfully.", "summary": new_text}


# ──────────────────────────────────────────────
# Telegram Bot Webhook (Background Processing)
# ──────────────────────────────────────────────

# Dedup set to prevent processing the same message twice on Telegram retries
_processed_messages = set()
_MAX_DEDUP_SIZE = 500


async def _process_telegram_url(chat_id: int, url: str):
    """Background task: summarize a URL and reply via Telegram."""
    try:
        if is_instagram_url(url):
            await send_typing_action(chat_id)
            audio_path = await asyncio.to_thread(download_audio, url)
            whisper_result = await asyncio.to_thread(transcribe_audio, audio_path)
            cleanup_audio(audio_path)
            cleaned_text = clean_transcript(whisper_result["text"])

            if not cleaned_text or len(cleaned_text) < 20:
                await send_telegram_message(chat_id, "❌ No meaningful speech found in this reel\\.")
                return

            if len(cleaned_text) > 30000:
                cleaned_text = cleaned_text[:30000]

            summary_data = await asyncio.to_thread(summarize_youtube, cleaned_text)
            result = {
                "title": summary_data["title"], "domain": "instagram.com",
                "difficulty": summary_data["difficulty"], "summary": summary_data["summary"],
                "key_points": summary_data["key_points"], "takeaway": summary_data["takeaway"],
                "original_url": url, "source_type": "instagram",
                "tools_mentioned": summary_data.get("tools_mentioned", []),
            }

        elif is_youtube_url(url):
            await send_typing_action(chat_id)
            transcript_data = await asyncio.to_thread(fetch_transcript, url)
            summary_data = await asyncio.to_thread(summarize_youtube, transcript_data["text"])
            result = {
                "title": summary_data["title"], "domain": "youtube.com",
                "difficulty": summary_data["difficulty"], "summary": summary_data["summary"],
                "key_points": summary_data["key_points"], "takeaway": summary_data["takeaway"],
                "original_url": url, "source_type": "youtube",
                "tools_mentioned": summary_data.get("tools_mentioned", []),
            }

        else:
            await send_typing_action(chat_id)
            article = await asyncio.to_thread(scrape_article, url)
            summary_data = await asyncio.to_thread(summarize_text, article["text"])
            result = {
                "title": summary_data["title"], "domain": article["domain"],
                "difficulty": summary_data["difficulty"], "summary": summary_data["summary"],
                "key_points": summary_data["key_points"], "takeaway": summary_data["takeaway"],
                "original_url": url, "source_type": "blog", "tools_mentioned": [],
            }

        # Save to DB
        try:
            row_id = save_summary(result)
            result["id"] = row_id
        except Exception:
            result["id"] = None

        # Send formatted summary reply
        reply = format_summary_for_telegram(result)
        await send_telegram_message(chat_id, reply)

    except Exception as e:
        error_msg = str(e).replace(".", "\\.").replace("!", "\\!").replace("-", "\\-")
        await send_telegram_message(
            chat_id,
            f"❌ Sorry, something went wrong:\n`{error_msg}`"
        )


async def _handle_telegram_message(message: dict):
    """
    Handle one incoming Telegram message.
    Shared by the webhook endpoint (Render) and the polling loop (local).
    """
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    message_id = message.get("message_id")
    user_first_name = message.get("from", {}).get("first_name", "there")

    if not chat_id:
        return

    print(f"💬 Telegram message from chat_id={chat_id}: {text[:80]!r}")

    # ── Dedup: skip if we already processed this exact message ──
    if message_id and message_id in _processed_messages:
        return
    if message_id:
        _processed_messages.add(message_id)
        # Prevent memory leak: trim the set if it gets too large
        if len(_processed_messages) > _MAX_DEDUP_SIZE:
            _processed_messages.clear()

    # Handle /start command
    if text.strip() == "/start":
        welcome = (
            f"👋 Hey {user_first_name}\\!\n\n"
            "I'm your *AI Knowledge Base Bot*\\.\n\n"
            "Send me any link and I'll summarize it:\n"
            "  📝 Blog articles\n"
            "  🎬 YouTube videos\n"
            "  📸 Instagram Reels\n\n"
            "Just paste a URL and I'll handle the rest\\!"
        )
        await send_telegram_message(chat_id, welcome)
        return

    # Handle /help command
    if text.strip() == "/help":
        help_text = (
            "🔧 *How to use me:*\n\n"
            "1\\. Send me any URL \\(blog, YouTube, Instagram\\)\n"
            "2\\. I'll scrape, transcribe, and summarize it\n"
            "3\\. Summary is saved to your dashboard\n\n"
            "Just paste a link and I'll do the rest\\!"
        )
        await send_telegram_message(chat_id, help_text)
        return

    # Extract URL from message
    url = extract_url_from_text(text)
    if not url:
        await send_telegram_message(
            chat_id,
            "🤔 I didn't find a URL in your message\\.\n\nSend me a blog, YouTube, or Instagram link to summarize\\!"
        )
        return

    # Acknowledge receipt immediately
    await send_telegram_message(
        chat_id,
        "⚡ Got it\\! Processing your link\\.\\.\\."
    )

    # ── Fire-and-forget: process in background ──
    asyncio.create_task(_process_telegram_url(chat_id, url))


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """
    Receive messages from Telegram Bot API (webhook mode, used on Render).
    Returns immediately to prevent Telegram retries, then processes in background.
    """
    data = await request.json()
    message = data.get("message", {})
    asyncio.create_task(_handle_telegram_message(message))
    return {"ok": True}



@app.get("/telegram-setup")
async def telegram_setup(webhook_url: str = ""):
    """
    Helper to register Telegram webhook and verify bot config.
    Usage: GET /telegram-setup?webhook_url=https://your-ngrok-url.ngrok-free.app/telegram-webhook
    """
    bot_info = await get_bot_info()

    if not webhook_url:
        return {
            "bot": bot_info,
            "instructions": "Pass ?webhook_url=https://your-domain/telegram-webhook to register.",
        }

    # Ensure webhook URL ends with /telegram-webhook
    if not webhook_url.endswith("/telegram-webhook"):
        webhook_url = webhook_url.rstrip("/") + "/telegram-webhook"

    result = await register_webhook(webhook_url)
    return {
        "bot": bot_info,
        "webhook_registration": result,
        "webhook_url": webhook_url,
    }
