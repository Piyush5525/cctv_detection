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
from api.core.config import SERVICE_LABELS, required_services
from api.services.dispatch_routing import build_dispatch_plan
from api.services.nearby_services import NearbyServicesError, get_nearby_services
from api.services.safety_guard import alerts_enabled_check, check_call_allowed, check_telegram_allowed

CALL_DISPATCH_URL = "https://omnidim.io/api/v1/calls/dispatch"


CATEGORY_SPOKEN = {"road_accident": "Crash", "crash": "Crash"}


def build_call_message(incident: dict, plan: Optional[dict]) -> str:
    """Text the Omnidim agent speaks ([alert_message]): demo prefix (DEMO_MODE), the category,
    the place, and the PRIMARY service for that category (DISPATCH_RULES), e.g.
    "Fire detected at MI Road, Jaipur. Nearest fire station: Rajasthan Agnishaman Seva, 1.61 kilometres."
    or "Crash detected at ... Nearest hospital: ...". Names and distances only, never phone numbers."""
    raw_category = str(incident.get("category", "incident"))
    category = CATEGORY_SPOKEN.get(raw_category) or raw_category.replace("_", " ").capitalize()
    place = incident.get("place_text") or incident.get("camera_name") or "unknown location"
    primary_type = required_services(raw_category)[0]
    label = SERVICE_LABELS[primary_type]
    primary = next((a for a in (plan or {}).get("assignments", []) if a.get("service_category") == primary_type), None)
    service = (primary or {}).get("service") or {}
    if primary and primary.get("status") == "available" and service.get("title"):
        nearest = f"Nearest {label}: {service['title']}, {float(service.get('distance_km') or 0):g} kilometres."
    else:
        nearest = f"Nearest {label}: unavailable."
    body = f"{category} detected at {place}. {nearest}"
    prefix = settings.CALL_MESSAGE_PREFIX.strip() if settings.DEMO_MODE else ""
    return f"{prefix} {body}".strip()


CAPTION_LIMIT = 1000  # Telegram's caption limit is 1024; keep a margin


def compose_caption(head: str, services: list, lines: list, footer: Optional[str] = None, limit: int = CAPTION_LIMIT) -> str:
    """head + "Nearest services: ..." + status lines (+ footer), always < 1024 chars.
    Truncation order: shorten the services list ("+N more"), then fall back to a pointer to
    the dashboard, then (only if head+status lines alone are too long) shorten the head.
    Status lines (what happened) are never cut before the services list is."""
    tail = ("\n\n" + "\n".join(lines[-6:])) if lines else ""
    if footer:
        tail += "\n" + footer
    items = [(x if len(x) <= 70 else x[:67] + "...") for x in services]

    def build(services_text: Optional[str]) -> str:
        return head + (f"\nNearest services: {services_text}" if services_text is not None else "") + tail

    if not services:
        text = build(None)
    else:
        text = None
        for count in range(len(items), 0, -1):
            more = f" (+{len(items) - count} more)" if count < len(items) else ""
            candidate = build("; ".join(items[:count]) + more)
            if len(candidate) <= limit:
                text = candidate
                break
        if text is None:
            text = build("see dashboard")
    if len(text) > limit:  # head or status lines themselves too long
        room = max(limit - len(tail) - 3, 0)
        text = head[:room].rstrip() + "..." + tail if room else text[:limit]
    return text[:limit]


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
        self._tg: dict[str, dict] = {}  # incident_id -> telegram message state

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

    def reset_state(self) -> None:
        """Demo reset: drop cooldown stamps, call-rate history and pending timers."""
        with self._lock:
            for timer in self._call_timers.values():
                timer.cancel()
            self._call_timers.clear()
            self._last_by_key.clear()
            self._calls.clear()

    # ------------------------------------------------------------------
    # Telegram message state: one entry per alert message so every button
    # press / escalation timer can edit the SAME message (original caption
    # kept, status lines appended, buttons that no longer apply removed).
    # ------------------------------------------------------------------
    @staticmethod
    def _stamp() -> str:
        t = datetime.now().astimezone()
        offset = t.strftime("%z")
        return f"{t:%H:%M:%S} UTC{offset[:3]}:{offset[3:]}"

    def _tg_register(self, incident_id: str, chat_id, message_id, photo: bool, head: str, services: list) -> None:
        with self._lock:
            self._tg[incident_id] = {"chat_id": chat_id, "message_id": message_id, "photo": photo, "head": head, "services": services,
                                     "lines": [], "ack": False, "fp": False, "call": False}

    def _tg_state_from_message(self, incident_id: str, message) -> Optional[dict]:
        """After an API restart the in-memory state is gone; rebuild it from the
        message the press came from (its current text already holds earlier lines)."""
        if message is None:
            return None
        with self._lock:
            if incident_id not in self._tg:
                text = getattr(message, "caption", None) or getattr(message, "text", None) or ""
                self._tg[incident_id] = {"chat_id": message.chat.id, "message_id": message.message_id,
                                         "photo": bool(getattr(message, "photo", None)), "head": text, "services": [],
                                         "lines": [], "ack": False, "fp": False, "call": False}
            return self._tg[incident_id]

    def _tg_markup(self, incident_id: str, state: dict):
        import telebot
        markup = telebot.types.InlineKeyboardMarkup()  # empty keyboard == buttons removed
        buttons = []
        if not state["ack"] and not state["fp"]:
            buttons.append(telebot.types.InlineKeyboardButton("Acknowledge (stops auto-call)", callback_data=f"incident:{incident_id}:confirm"))
        if not state["fp"]:
            buttons.append(telebot.types.InlineKeyboardButton("False alarm", callback_data=f"incident:{incident_id}:false_alarm"))
        if buttons:
            markup.row(*buttons)
        if not state["call"] and not state["ack"] and not state["fp"]:
            markup.row(telebot.types.InlineKeyboardButton("Escalate now", callback_data=f"incident:{incident_id}:escalate"))
        return markup

    def _tg_edit(self, incident_id: str) -> None:
        with self._lock:
            state = self._tg.get(incident_id)
            if state is None:
                return
            text = compose_caption(state["head"], state["services"], state["lines"])
            snapshot = dict(state)
        bot = self._get_bot()
        if bot is None:
            return
        try:
            markup = self._tg_markup(incident_id, snapshot)
            if snapshot["photo"]:
                bot.edit_message_caption(text, chat_id=snapshot["chat_id"], message_id=snapshot["message_id"], reply_markup=markup)
            else:
                bot.edit_message_text(text, chat_id=snapshot["chat_id"], message_id=snapshot["message_id"], reply_markup=markup)
        except Exception as exc:
            if "not modified" not in str(exc).lower():
                print(f"[Notification] telegram message edit failed: {type(exc).__name__}")

    def _tg_note(self, incident_id: str, line: Optional[str] = None, **flags) -> None:
        """Append a status line and/or set flags (ack/fp/call), then edit the message."""
        with self._lock:
            state = self._tg.get(incident_id)
            if state is None:
                return
            if line:
                state["lines"].append(line)
            state.update(flags)
        self._tg_edit(incident_id)

    def process_press(self, incident_id: str, action: str, presser: Optional[str] = None, message=None, edit: bool = True) -> dict:
        """Apply one operator button press. Returns {"ok", "answer"}; `answer` is
        the text for answerCallbackQuery. Unknown incident => "This alert has expired"."""
        from api.services import incident_service_v2 as incident_service
        from api.models.incident_v2 import IncidentStatus, IncidentStatusUpdate
        name = presser or "operator"
        if action not in {"confirm", "false_alarm", "escalate"}:
            return {"ok": False, "answer": "Unknown action"}
        incident = incident_service.get_incident(incident_id)
        if incident is None:
            state = self._tg_state_from_message(incident_id, message)
            if state is not None:
                with self._lock:
                    state["lines"].append(f"This alert has expired (incident no longer exists) - {self._stamp()}")
                    state.update(ack=True, fp=True, call=True)
                if edit:
                    self._tg_edit(incident_id)
            return {"ok": False, "answer": "This alert has expired"}
        self._tg_state_from_message(incident_id, message)
        stamp = self._stamp()
        with self._lock:
            timer = self._call_timers.pop(incident_id, None)
            if timer is not None:
                timer.cancel()
        if action == "escalate":
            self._record(incident_id, "operator", "escalate", "telegram_operator", "immediate escalation requested")
            self._tg_note_noedit(incident_id, f"Escalate now pressed by {name} at {stamp}")
            if edit:
                self._tg_edit(incident_id)
            threading.Thread(target=self._send_call_if_still_needed, args=(incident_id, incident, "operator"), daemon=True).start()
            return {"ok": True, "answer": "Escalating: placing the call"}
        update = IncidentStatusUpdate(status=IncidentStatus.CONFIRMED if action == "confirm" else IncidentStatus.FALSE_POSITIVE,
                                      reviewed_by="telegram_operator", review_note=f"Telegram callback: {action}")
        if incident_service.update_status(incident_id, update) is None:
            return {"ok": False, "answer": "This alert has expired"}
        label = "acknowledged" if action == "confirm" else action
        self._record(incident_id, "operator", label, "telegram_operator", "callback received")
        if timer is not None:
            self._record(incident_id, "call", "cancelled", "configured demo phone", f"automatic call cancelled by operator ({label})")
        suffix = " - automatic call cancelled" if timer is not None else ""
        if action == "confirm":
            self._tg_note_noedit(incident_id, f"Acknowledged by {name} at {stamp}{suffix}", ack=True)
        else:
            self._tg_note_noedit(incident_id, f"Marked false alarm by {name} at {stamp}{suffix}", fp=True)
        if edit:
            self._tg_edit(incident_id)
        return {"ok": True, "answer": "Acknowledged" if action == "confirm" else "Marked as false alarm"}

    def _tg_note_noedit(self, incident_id: str, line: str, **flags) -> None:
        with self._lock:
            state = self._tg.get(incident_id)
            if state is None:
                return
            state["lines"].append(line)
            state.update(flags)

    def handle_callback(self, incident_id: str, action: str) -> bool:
        """Compatibility wrapper (no Telegram message context). Callback data is
        restricted to the three known actions; anything else is rejected."""
        return bool(self.process_press(incident_id, action)["ok"])

    def _on_callback(self, call) -> None:
        """Telegram callback_query handler: answer immediately, then edit the message."""
        parts = str(getattr(call, "data", "")).split(":", 2)
        bot = self._get_bot()
        if len(parts) != 3:
            result = {"ok": False, "answer": "Unknown action"}
        else:
            user = getattr(call, "from_user", None)
            presser = " ".join(x for x in (getattr(user, "first_name", None), getattr(user, "last_name", None)) if x) \
                or getattr(user, "username", None) or "operator"
            result = self.process_press(parts[1], parts[2], presser, getattr(call, "message", None), edit=False)
        try:
            if bot is not None:
                bot.answer_callback_query(call.id, result["answer"])
        except Exception:
            pass
        if len(parts) == 3:
            self._tg_edit(parts[1])

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
                "required_services": list(required_services(category)),
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
        nearest = []  # only the services this category needs (plan is built from DISPATCH_RULES)
        for item in plan.get("assignments", []):
            label = SERVICE_LABELS.get(item.get("service_category"), str(item.get("service_category")))
            service = item.get("service") or {}
            if item.get("status") == "available" and service.get("title"):
                nearest.append(f"{label}: {service['title']} ({service.get('distance_km', '?')} km)")
            else:
                nearest.append(f"{label}: none found nearby")
        head = (f"Incident: {incident['category']}\nCamera: {incident['camera_name']}\nPlace: {incident['place_text']}\n"
                f"Time: {incident.get('detected_at', _now())}\nPeak confidence: {incident['detection']['peak_confidence']:.2f}\n"
                f"Threshold: {incident['detection']['threshold_applied']:.2f}")
        services = nearest or ["unavailable"]
        caption = compose_caption(head, services, [], footer="Tap Acknowledge to stop the automatic call; False alarm to dismiss it.")
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
                        sent = bot.send_photo(chat_id, photo, caption=caption, reply_markup=markup)
                    is_photo = True
                else:
                    sent = bot.send_message(chat_id, caption, reply_markup=markup)
                    is_photo = False
                self._tg_register(incident_id, chat_id, getattr(sent, "message_id", None), is_photo, head, services)
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

    def _send_call_if_still_needed(self, incident_id: str, incident: dict, source: str = "auto") -> None:
        """source="auto": the escalation timer fired (no response). source="operator":
        the Escalate-now button. The Telegram message gets a status line either way."""
        from api.services import incident_service_v2 as incident_service
        auto = source == "auto"
        who = "auto-call" if auto else "call"

        def skipped(reason: str) -> None:
            self._tg_note(incident_id, f"{who} skipped: {reason}")

        current = incident_service.get_incident(incident_id)
        if current is None or current.get("status") in ("false_positive", "confirmed"):
            # "confirmed" == Acknowledge: stops the automatic call whether it was
            # pressed in Telegram or on the dashboard (the press already wrote its own line).
            self._record(incident_id, "call", "cancelled", "configured demo phone", "incident acknowledged, marked false positive or unavailable")
            if current is not None:
                self._tg_note(incident_id, f"{who} cancelled: incident already {'acknowledged' if current.get('status') == 'confirmed' else 'dismissed'}")
            return
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] > 3600:
                self._calls.popleft()
            capped = len(self._calls) >= settings.MAX_CALLS_PER_HOUR
        if capped:
            self._record(incident_id, "call", "skipped", "configured demo phone", "MAX_CALLS_PER_HOUR reached")
            return skipped("MAX_CALLS_PER_HOUR reached")
        phone = settings.DEMO_PHONE_NUMBER
        gate = check_call_allowed(phone)
        if not gate.allowed:
            self._record(incident_id, "call", "blocked", "configured demo phone", gate.reason)
            return skipped(gate.reason)
        api_key, agent_id = os.environ.get("OMNIDIM_API_KEY"), os.environ.get("OMNIDIM_AGENT_ID")
        if not api_key or not agent_id:
            self._record(incident_id, "call", "failed", "configured demo phone", "missing OMNIDIM_API_KEY or OMNIDIM_AGENT_ID")
            return skipped("missing OMNIDIM_API_KEY or OMNIDIM_AGENT_ID")
        payload = {"agent_id": int(agent_id), "to_number": phone,
                   "call_context": {"alert_message": build_call_message(incident, current.get("dispatch_plan"))}}
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
            line = f"No response - auto-call placed at {self._stamp()}" if auto else f"Call placed at {self._stamp()}"
            self._tg_note(incident_id, line, call=True)  # Acknowledge / False alarm stay available
        except (requests.RequestException, ValueError) as exc:
            self._record(incident_id, "call", "failed", "configured demo phone", type(exc).__name__)
            skipped(f"call request failed ({type(exc).__name__})")

    def _start_polling(self) -> None:
        """Callback poller for the lifetime of the API: restarts itself if the
        polling loop ever dies, so button presses work at any time."""
        if self._poller is not None and self._poller.is_alive():
            return
        bot = self._get_bot()
        if bot is None:
            return
        if not self._handlers_registered:
            bot.callback_query_handler(func=lambda call: str(getattr(call, "data", "")).startswith("incident:"))(self._on_callback)
            self._handlers_registered = True

        def run():
            while not self._stop.is_set():
                try:
                    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20,
                                         allowed_updates=["callback_query", "message"])
                except Exception as exc:
                    print(f"[Notification] telegram poller stopped ({type(exc).__name__}); restarting in 5 s")
                if not self._stop.wait(5):
                    continue

        self._poller = threading.Thread(target=run, name="telegram-callback-poller", daemon=True)
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
