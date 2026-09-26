import os
import telebot
import cv2
import time

# Initialize the Telegram bot
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

ALERT_COOLDOWN_SECONDS = 60
# Cooldown is tracked per alert category (see `reason` below), not globally --
# otherwise one alert type (e.g. a fall) could silently block a genuinely
# different alert (e.g. surrounded) that happens moments later.
_last_alert_time = {}


def send_telegram_alert(frame, message, reason: str = "general"):
    print("telegram alert started")

    if not bot or not CHAT_ID:
        print("Telegram alert skipped: missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars.")
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
