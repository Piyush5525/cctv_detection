import os
import time
import requests

from api.core.config import settings

# --- Configuration (all values come from environment variables) ---
# OMNIDIM_API_KEY      -> from https://omnidim.io/api-management
# OMNIDIM_AGENT_ID     -> the AI voice agent you configured in Omnidimension (integer)
# OMNIDIM_FROM_NUMBER_ID -> ID of the phone number you purchased on your Omnidimension account (integer, optional)
# ALERT_PHONE_NUMBER   -> the number to call in E.164 format, e.g. +919876543210
OMNIDIM_API_KEY = os.getenv("OMNIDIM_API_KEY")
OMNIDIM_AGENT_ID = os.getenv("OMNIDIM_AGENT_ID")
OMNIDIM_FROM_NUMBER_ID = os.getenv("OMNIDIM_FROM_NUMBER_ID")
ALERT_PHONE_NUMBER = os.getenv("ALERT_PHONE_NUMBER")

OMNIDIM_DISPATCH_URL = "https://omnidim.io/api/v1/calls/dispatch"

CALL_COOLDOWN_SECONDS = 120  # avoid spamming calls; separate cooldown from the Telegram alert
# Tracked per alert category so one alert type can't block a different one (see Telebot_Alert.py).
_last_call_time = {}

# Phase 1c follow-ups item 1: same ALERTS_ENABLED gate as Telebot_Alert.py,
# logged once per process run rather than once per call.
_disabled_notice_logged = False


def send_call_alert(message: str, reason: str = "general"):
    """Triggers an outbound AI voice call via Omnidimension."""
    global _disabled_notice_logged
    if not settings.ALERTS_ENABLED:
        if not _disabled_notice_logged:
            print("[Call_Alert] ALERTS_ENABLED is false -- alerts disabled for this run.")
            _disabled_notice_logged = True
        return

    print("call alert started")

    if not all([OMNIDIM_API_KEY, OMNIDIM_AGENT_ID, ALERT_PHONE_NUMBER]):
        print("Call alert skipped: missing one of OMNIDIM_API_KEY / OMNIDIM_AGENT_ID / ALERT_PHONE_NUMBER env vars.")
        return

    current_time = time.time()
    last_time = _last_call_time.get(reason, 0)
    if current_time - last_time < CALL_COOLDOWN_SECONDS:
        print("Waiting to place next call. Time since last call:", int(current_time - last_time), "seconds")
        return

    headers = {
        "Authorization": f"Bearer {OMNIDIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "agent_id": int(OMNIDIM_AGENT_ID),
        "to_number": ALERT_PHONE_NUMBER,
        # Key name must exactly match the [variable] used in the agent's
        # welcome message on the OmniDimension dashboard, e.g. [alert_message].
        "call_context": {
            "alert_message": message,
        },
    }
    if OMNIDIM_FROM_NUMBER_ID:
        payload["from_number_id"] = int(OMNIDIM_FROM_NUMBER_ID)

    try:
        response = requests.post(OMNIDIM_DISPATCH_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        _last_call_time[reason] = current_time
        print(f"Call alert triggered: {message}")
    except requests.exceptions.RequestException as e:
        print(f"Error triggering call alert: {e}")
        if e.response is not None:
            print(f"Response body: {e.response.text}")
