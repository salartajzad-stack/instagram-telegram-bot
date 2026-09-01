import asyncio
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from yt_dlp import YoutubeDL


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)

INSTAGRAM_URL = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/[^\s/?#]+[^\s]*",
    re.IGNORECASE,
)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "49"))
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


def ydl_options(download_dir: Path) -> dict:
    options = {
        "outtmpl": str(download_dir / "%(title).80s-%(id)s.%(ext)s"),
        "format": "bestvideo[filesize<45M]+bestaudio/best[filesize<45M]/best",
        "merge_output_format": "mp4",
        "noplaylist": False,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 2,
    }
    cookie_file = os.getenv("INSTAGRAM_COOKIES_FILE")
    if cookie_file:
        options["cookiefile"] = cookie_file
    return options


def download_media(url: str, download_dir: Path) -> list[Path]:
    with YoutubeDL(ydl_options(download_dir)) as ydl:
        ydl.download([url])
    return sorted(
        file for file in download_dir.iterdir()
        if file.is_file() and file.suffix.lower() not in {".part", ".ytdl"}
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "سلام 👋\nلینک پست یا ریلز عمومی اینستاگرام را بفرست تا فایلش را برایت ارسال کنم."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "لینک کامل پست یا ریلز عمومی Instagram را در یک پیام بفرست. "
        "این ربات برای محتوای خصوصی یا بدون اجازه صاحب اثر طراحی نشده است."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    match = INSTAGRAM_URL.search(message.text or "")
    if not match:
        await message.reply_text("لطفاً یک لینک معتبر پست یا ریلز اینستاگرام بفرست.")
        return

    url = match.group(0)
    status = await message.reply_text("⏳ در حال دریافت فایل…")
    work_dir = Path(tempfile.mkdtemp(prefix="igbot-"))

    try:
        async with DOWNLOAD_SEMAPHORE:
            await context.bot.send_chat_action(message.chat_id, ChatAction.UPLOAD_DOCUMENT)
            files = await asyncio.to_thread(download_media, url, work_dir)

        if not files:
            raise RuntimeError("هیچ فایلی دریافت نشد")

        sent = 0
        for file in files:
            size_mb = file.stat().st_size / (1024 * 1024)
            if size_mb > MAX_UPLOAD_MB:
                await message.reply_text(
                    f"فایل «{file.name}» حدود {size_mb:.1f} مگابایت است و از سقف ارسال ربات بزرگ‌تر است."
                )
                continue
            with file.open("rb") as media:
                if file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                    await message.reply_photo(photo=media)
                elif file.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
                    await message.reply_video(video=media, supports_streaming=True)
                else:
                    await message.reply_document(document=media)
            sent += 1

        if sent:
            await status.edit_text("✅ انجام شد")
        else:
            await status.edit_text("فایل دریافت شد، اما برای ارسال در تلگرام بیش از حد بزرگ بود.")
    except Exception as exc:
        LOGGER.exception("Download failed: %s", exc)
        await status.edit_text(
            "❌ دانلود انجام نشد. ممکن است پست خصوصی، حذف‌شده یا موقتاً محدود شده باشد."
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
