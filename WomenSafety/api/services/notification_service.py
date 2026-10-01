"""Bounded, asynchronous notification delivery for v2 incidents.

Only configured demo recipients can receive outbound traffic.  Lookup results
are used to form an operator-facing dispatch plan; their phone numbers never
enter the call path.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from typing import Optional

import requests

from api.core.config import settings
from api.services.dispatch_routing import REQUIRED_SERVICES, build_dispatch_plan
from api.services.nearby_services import NearbyServicesError, get_nearby_services
from api.services.safety_guard import alerts_enabled_check, check_call_allowed, check_telegram_allowed

CALL_DISPATCH_URL = "https://omnidim.io/api/v1/calls/dispatch"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotificationService:
    def __init__(self) -> None:
        self._queue: Queue = Queue(maxsize=settings.NOTIFICATION_QUEUE_MAX_SIZE)
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._poller: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._last_by_key: dict[tuple[str, str], float] = {}
        self._calls: deque[float] = deque()
        self._call_timers: dict[str, threading.Timer] = {}
        self._bot = None
        self._handlers_registered = False

    def start(self, start_polling: bool = False) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._stop.clear()
                self._worker = threading.Thread(target=self._run, name="notification-worker", daemon=True)
                self._worker.start()
            if start_polling:
                self._start_polling()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for timer in self._call_timers.values():
                timer.cancel()
            self._call_timers.clear()
            bot = self._get_bot()
            if bot is not None:
                try:
                    bot.stop_polling()
                except Exception:
                    pass
        if self._worker is not None:
            self._worker.join(timeout=3)
        if self._poller is not None:
            self._poller.join(timeout=3)

    def enqueue(self, incident) -> bool:
        """Queue one incident; caller never waits for network I/O.
        Always queues (cooldown is applied later, to outbound only)."""
        self.start()
        try:
            self._queue.put_nowait(incident.to_dict() if hasattr(incident, "to_dict") else incident)
            self._record(incident.incident_id, "dispatch", "queued", "internal", "queued for dispatch planning")
            return True
        except Full:
            self._record(incident.incident_id, "dispatch", "failed", "internal", "notification queue is full")
            return False

    def _cooldown_seconds(self) -> float:
        return settings.DEMO_COOLDOWN_S if settings.DEMO_MODE else settings.NOTIFICATION_COOLDOWN_S

    def _cooldown_active(self, key: tuple) -> bool:
        """True if an outbound alert for this camera+category went out within
        the cooldown window; otherwise stamps now and returns False."""
        now = time.monotonic()
        with self._lock:
            previous = self._last_by_key.get(key)
            if previous is not None and now - previous < self._cooldown_seconds():
                return True
            self._last_by_key[key] = now
            return False

    def handle_callback(self, incident_id: str, action: str) -> bool:
        """Apply an operator decision from a signed-in bot callback.

        Callback data is intentionally restricted to the two known actions;
        anything else is rejected instead of becoming a free-form status API.
        """
        if action == "escalate":
            from api.services import incident_service_v2 as incident_service
            incident = incident_service.get_incident(incident_id)
            if incident is None:
                return False
            with self._lock:
                timer = self._call_timers.pop(incident_id, None)
                if timer is not None:
                    timer.cancel()
            self._record(incident_id, "operator", "escalate", "telegram_operator", "immediate escalation requested")
            threading.Thread(target=self._send_call_if_still_needed, args=(incident_id, incident), daemon=True).start()
            return True
        if action not in {"confirm", "false_alarm"}:
            return False
        from api.services import incident_service_v2 as incident_service
        from api.models.incident_v2 import IncidentStatus, IncidentStatusUpdate
        update = IncidentStatusUpdate(status=IncidentStatus.CONFIRMED if action == "confirm" else IncidentStatus.FALSE_POSITIVE,
                                      reviewed_by="telegram_operator", review_note=f"Telegram callback: {action}")
        changed = incident_service.update_status(incident_id, update)
        if changed is None:
            return False
        with self._lock:
            timer = self._call_timers.pop(incident_id, None)
            if timer is not None:
                timer.cancel()
        label = "acknowledged" if action == "confirm" else action
        self._record(incident_id, "operator", label, "telegram_operator", "callback received")
        if timer is not None:
            self._record(incident_id, "call", "cancelled", "configured demo phone", f"automatic call cancelled by operator ({label})")
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                incident = self._queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                self._process(incident)
            except Exception as exc:
                self._record(incident.get("incident_id", "unknown"), "dispatch", "failed", "internal", type(exc).__name__)
            finally:
                self._queue.task_done()

    def _process(self, incident: dict) -> None:
        incident_id = incident["incident_id"]
        category = incident["category"]
        try:
            lookup = get_nearby_services(incident["camera_id"], incident["latitude"], incident["longitude"], incident["place_text"])
            plan = build_dispatch_plan(category, incident["latitude"], incident["longitude"], lookup.get("services", {}))
            plan["nearby_services_source"] = lookup.get("source")
            if lookup.get("errors"):
                plan["lookup_errors"] = lookup["errors"]
        except NearbyServicesError as exc:
            # A real lookup failure stays visible; no fake services or routes.
            plan = {
                "category": category,
                "required_services": list(REQUIRED_SERVICES.get(category, REQUIRED_SERVICES["other"])),
                "assignments": [], "lookup_error": str(exc),
                "contact_policy": "display_only_never_auto_dial_discovered_numbers", "created_at": _now(),
            }
        self._set_dispatch_plan(incident_id, plan)

        enabled = alerts_enabled_check()
        if not enabled.allowed:
            self._record(incident_id, "telegram", "skipped", "configured demo chat", enabled.reason)
            self._record(incident_id, "call", "skipped", "configured demo phone", enabled.reason)
            return
        # Fix pass item 6: cooldown applies ONLY to outbound Telegram/call.
        # The incident and dispatch plan above are always created; a
        # suppressed outbound is recorded in the timeline.
        if self._cooldown_active((incident["camera_id"], category)):
            self._record(incident_id, "telegram", "suppressed", "configured demo chat", "suppressed: cooldown")
            self._record(incident_id, "call", "suppressed", "configured demo phone", "suppressed: cooldown")
            return
        self._send_telegram(incident, plan)
        # A high-confidence detection bypasses the wait. Otherwise the call
        # remains an escalation only if no operator has dismissed it.
        confidence = float(incident.get("detection", {}).get("peak_confidence", 0.0))
        configured_delay = settings.DEMO_ESCALATION_DELAY_S if settings.DEMO_MODE else settings.ESCALATION_DELAY_S
        delay = 0.0 if confidence >= settings.CALL_MIN_CONFIDENCE else configured_delay
        self._schedule_call(incident_id, incident, delay)

    def _get_bot(self):
        if self._bot is not None:
            return self._bot
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return None
        try:
            import telebot
            self._bot = telebot.TeleBot(token)
            return self._bot
        except Exception:
            return None

    def _send_telegram(self, incident: dict, plan: dict) -> bool:
        incident_id = incident["incident_id"]
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        gate = check_telegram_allowed(chat_id)
        if not gate.allowed:
            self._record(incident_id, "telegram", "blocked", "configured demo chat", gate.reason)
            return False
        bot = self._get_bot()
        if bot is None:
            self._record(incident_id, "telegram", "failed", "configured demo chat", "missing TELEGRAM_BOT_TOKEN")
            return False
        dispatch = ", ".join(f"{item['service_category']}: {item.get('status')}" for item in plan.get("assignments", []))
        caption = (f"Incident: {incident['category']}\nCamera: {incident['camera_name']}\nPlace: {incident['place_text']}\n"
                   f"Time: {incident.get('detected_at', _now())}\nPeak confidence: {incident['detection']['peak_confidence']:.2f}\n"
                   f"Threshold: {incident['detection']['threshold_applied']:.2f}\nDispatch: {dispatch or 'unavailable'}\n"
                   "Tap Acknowledge to stop the automatic call; False alarm to dismiss it.")
        try:
            import telebot
            markup = telebot.types.InlineKeyboardMarkup()
            markup.row(telebot.types.InlineKeyboardButton("Acknowledge (stops auto-call)", callback_data=f"incident:{incident_id}:confirm"),
                       telebot.types.InlineKeyboardButton("False alarm", callback_data=f"incident:{incident_id}:false_alarm"))
            markup.row(telebot.types.InlineKeyboardButton("Escalate now", callback_data=f"incident:{incident_id}:escalate"))
        except Exception:
            markup = None
        evidence_path = incident.get("evidence", {}).get("best_frame_path")
        for attempt in range(settings.NOTIFICATION_MAX_RETRIES):
            try:
                if evidence_path and os.path.exists(evidence_path):
                    with open(evidence_path, "rb") as photo:
                        bot.send_photo(chat_id, photo, caption=caption, reply_markup=markup)
                else:
                    bot.send_message(chat_id, caption, reply_markup=markup)
                bot.send_location(chat_id, incident["latitude"], incident["longitude"])
                self._record(incident_id, "telegram", "sent", "configured demo chat", None)
                return True
            except Exception as exc:
                if attempt + 1 == settings.NOTIFICATION_MAX_RETRIES:
                    self._record(incident_id, "telegram", "failed", "configured demo chat", type(exc).__name__)
                    return False
                time.sleep(settings.NOTIFICATION_RETRY_BACKOFF_S * (attempt + 1))
        return False

    def _schedule_call(self, incident_id: str, incident: dict, delay: float) -> None:
        def deliver():
            with self._lock:
                self._call_timers.pop(incident_id, None)
            self._send_call_if_still_needed(incident_id, incident)
        timer = threading.Timer(delay, deliver)
        timer.daemon = True
        with self._lock:
            self._call_timers[incident_id] = timer
        self._record(incident_id, "call", "scheduled", "configured demo phone", f"escalation delay {delay:g}s")
        timer.start()

    def _send_call_if_still_needed(self, incident_id: str, incident: dict) -> None:
        from api.services import incident_service_v2 as incident_service
        current = incident_service.get_incident(incident_id)
        if current is None or current.get("status") in ("false_positive", "confirmed"):
            # "confirmed" == Acknowledge (fix pass item 14): stops the automatic call
            # whether it was pressed in Telegram or on the dashboard.
            self._record(incident_id, "call", "cancelled", "configured demo phone", "incident acknowledged, marked false positive or unavailable")
            return
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] > 3600:
                self._calls.popleft()
            if len(self._calls) >= settings.MAX_CALLS_PER_HOUR:
                self._record(incident_id, "call", "skipped", "configured demo phone", "MAX_CALLS_PER_HOUR reached")
                return
        phone = settings.DEMO_PHONE_NUMBER
        gate = check_call_allowed(phone)
        if not gate.allowed:
            self._record(incident_id, "call", "blocked", "configured demo phone", gate.reason)
            return
        api_key, agent_id = os.environ.get("OMNIDIM_API_KEY"), os.environ.get("OMNIDIM_AGENT_ID")
        if not api_key or not agent_id:
            self._record(incident_id, "call", "failed", "configured demo phone", "missing OMNIDIM_API_KEY or OMNIDIM_AGENT_ID")
            return
        payload = {"agent_id": int(agent_id), "to_number": phone,
                   "call_context": {"alert_message": f"{incident['category']} at {incident['camera_name']}"}}
        from_number_id = os.environ.get("OMNIDIM_FROM_NUMBER_ID")
        if from_number_id:
            payload["from_number_id"] = int(from_number_id)
        try:
            response = requests.post(CALL_DISPATCH_URL, json=payload,
                                     headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=15)
            response.raise_for_status()
            with self._lock:
                self._calls.append(time.monotonic())
            self._record(incident_id, "call", "sent", "configured demo phone", None)
        except (requests.RequestException, ValueError) as exc:
            self._record(incident_id, "call", "failed", "configured demo phone", type(exc).__name__)

    def _start_polling(self) -> None:
        if self._poller is not None and self._poller.is_alive():
            return
        bot = self._get_bot()
        if bot is None:
            return
        if not self._handlers_registered:
            @bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("incident:"))
            def _callback(call):
                parts = str(call.data).split(":", 2)
                success = len(parts) == 3 and self.handle_callback(parts[1], parts[2])
                try:
                    bot.answer_callback_query(call.id, "Recorded" if success else "Incident/action unavailable")
                except Exception:
                    pass
            self._handlers_registered = True
        self._poller = threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20),
                                        name="telegram-callback-poller", daemon=True)
        self._poller.start()

    @staticmethod
    def _record(incident_id: str, channel: str, status: str, recipient: str, detail: Optional[str]) -> None:
        from api.services import incident_service_v2 as incident_service
        incident_service.append_notification(incident_id, {
            "channel": channel, "status": status, "at": _now(), "recipient": recipient, "detail": detail,
        })

    @staticmethod
    def _set_dispatch_plan(incident_id: str, plan: dict) -> None:
        from api.services import incident_service_v2 as incident_service
        incident_service.set_dispatch_plan(incident_id, plan)


notification_service = NotificationService()
