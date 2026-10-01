import os
import telebot
import cv2
import time

from api.core.config import settings
from api.services.safety_guard import check_telegram_allowed

# Initialize the Telegram bot
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

ALERT_COOLDOWN_SECONDS = 60
# Cooldown is tracked per alert category (see `reason` below), not globally --
# otherwise one alert type (e.g. a fall) could silently block a genuinely
# different alert (e.g. surrounded) that happens moments later.
_last_alert_time = {}

# Phase 1c follow-ups item 1: ALERTS_ENABLED defaults to False (config).
# Logged exactly once per process run, not once per call -- a live loop
# calls this function every time a detector fires, and repeating "alerts
# disabled" on every single one of those would be log spam, not a
# useful signal.
_disabled_notice_logged = False


def send_telegram_alert(frame, message, reason: str = "general"):
    global _disabled_notice_logged
    if not settings.ALERTS_ENABLED:
        if not _disabled_notice_logged:
            print("[Telebot_Alert] ALERTS_ENABLED is false -- alerts disabled for this run.")
            _disabled_notice_logged = True
        return

    print("telegram alert started")

    if not bot or not CHAT_ID:
        print("Telegram alert skipped: missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars.")
        return

    # Dispatch Backend phase: same safety layer the new notification
    # service uses. For Telegram this only matters once a future feature
    # might add more recipients than the single configured CHAT_ID --
    # today it is a no-op in practice (TELEGRAM_CHAT_ID_ALLOWLIST
    # defaults to CHAT_ID itself when unset), kept for consistency with
    # the call path and so both channels are provably on the same rail.
    safety = check_telegram_allowed(CHAT_ID)
    if not safety.allowed:
        print(f"[Telebot_Alert] message BLOCKED by safety_guard: {safety.reason}")
        return

    current_time = time.time()
    last_time = _last_alert_time.get(reason, 0)

    if current_time - last_time >= ALERT_COOLDOWN_SECONDS:
        try:
            cv2.imwrite("alert.jpg", frame)
            with open("alert.jpg", 'rb') as photo:
                bot.send_photo(CHAT_ID, photo, caption=f"🚨 ALERT! 🚨\n{message}")
            bot.send_message(CHAT_ID, f"{message} Please take necessary precautions immediately!")
            _last_alert_time[reason] = current_time
            print(f"Telegram alert sent: {message}")
        except Exception as e:
            print(f"Error sending Telegram alert: {e}")
    else:
        print("Waiting to send next alert. Time since last alert:", int(current_time - last_time), "seconds")
