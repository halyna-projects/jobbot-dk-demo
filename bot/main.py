import asyncio
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import handlers, storage
from bot.config import EXCLUDED_TELEGRAM_IDS, INACTIVE_DATA_RETENTION_DAYS, TELEGRAM_BOT_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Without this, an exception (e.g. a transient network timeout talking
    # to Telegram) just gets logged and the user is left staring at
    # nothing with no idea anything went wrong.
    logger.exception("Unhandled exception while processing update", exc_info=context.error)

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Der gik noget galt (formentlig en netværksfejl). Prøv igen."
            )
        except Exception:
            logger.exception("Could not even notify the user about the earlier error")


async def cleanup_inactive_users(context: ContextTypes.DEFAULT_TYPE):
    deleted = await asyncio.to_thread(
        storage.delete_inactive_users, INACTIVE_DATA_RETENTION_DAYS, EXCLUDED_TELEGRAM_IDS
    )
    if deleted:
        logger.info("Privacy cleanup: deleted %s inactive user(s)", deleted)


# Recently-active window for the restart notice below -- long enough to
# catch someone genuinely mid-conversation, short enough not to spam
# someone who used the bot an hour ago and is long gone.
RESTART_NOTICE_WINDOW_MINUTES = 5
RESTART_NOTICE_TEXT = (
    "🔧 Botten opdateres lige nu (ny version deployes) — det tager typisk "
    "under et minut. Hvis du var midt i noget, så prøv igen om lidt."
)


async def notify_active_users_before_restart(app: Application):
    # Runs after polling has stopped but before the bot's own connection is
    # torn down, so this is the last reliable moment to actually send
    # anything -- a redeploy otherwise just kills the process with no
    # warning, which looked exactly like a hang from the outside.
    try:
        ids = await asyncio.to_thread(
            storage.get_recently_active_telegram_ids, RESTART_NOTICE_WINDOW_MINUTES
        )
    except Exception:
        logger.exception("Could not look up recently active users before restart")
        return

    for telegram_id in ids:
        try:
            await app.bot.send_message(telegram_id, RESTART_NOTICE_TEXT)
        except Exception:
            logger.warning("Could not notify %s before restart", telegram_id)


def main():
    storage.init_db()

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(20)
        .read_timeout(20)
        .get_updates_connect_timeout(20)
        .get_updates_read_timeout(20)
        .post_stop(notify_active_users_before_restart)
        .build()
    )

    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("keywords", handlers.set_keywords))
    app.add_handler(CommandHandler("location", handlers.set_location))
    app.add_handler(CommandHandler("cv", handlers.cv_status))
    app.add_handler(CommandHandler("search", handlers.run_search))
    app.add_handler(CommandHandler("reset", handlers.reset_seen))
    app.add_handler(CommandHandler("apply", handlers.apply_to_vacancy))
    app.add_handler(CommandHandler("stats", handlers.stats))
    app.add_handler(CallbackQueryHandler(handlers.handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handlers.handle_cv_upload))
    app.add_handler(MessageHandler(filters.PHOTO, handlers.handle_photo))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_plain_text)
    )
    app.add_error_handler(error_handler)

    if app.job_queue is not None:
        app.job_queue.run_repeating(
            cleanup_inactive_users, interval=86400, first=60
        )
    else:
        logger.warning(
            "JobQueue not available (python-telegram-bot[job-queue] not "
            "installed) -- inactive-user privacy cleanup will not run."
        )

    logging.info("Bot starting (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
