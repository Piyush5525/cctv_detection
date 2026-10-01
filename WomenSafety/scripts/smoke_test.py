"""Explicit, opt-in LIVE smoke tests. Nothing runs unless you pass a channel
flag AND --yes. Recipients are ONLY the allowlisted ones:
  * Telegram -> TELEGRAM_CHAT_ID (must pass safety_guard.check_telegram_allowed)
  * Call     -> DEMO_PHONE_NUMBER (must pass safety_guard.check_call_allowed,
                i.e. never 100/101/102/108/112, never anything but the demo number)
Secrets, phone numbers and chat ids are never printed (phone: last 2 digits).

Examples:
  python scripts/smoke_test.py --serpapi --yes     # 3 SerpApi queries (hospital/police/fire) for one camera, then cached
  python scripts/smoke_test.py --mapbox  --yes     # 1 Directions request
  python scripts/smoke_test.py --telegram --yes    # 1 photo + location pin + 3 buttons, waits 60 s for a press
  python scripts/smoke_test.py --call --yes        # places ONE call to DEMO_PHONE_NUMBER

Stop the API server before --telegram: two processes long-polling one bot
token conflict (Telegram returns 409).
"""
import argparse
import os
import sys
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from api.core.config import settings  # noqa: E402  (loads .env)
from api.models.camera import get_camera  # noqa: E402
from api.services.safety_guard import check_call_allowed, check_telegram_allowed  # noqa: E402

PHOTO = ROOT / "data" / "7.jpg"
RESULTS = []


def report(name, ok, detail):
    RESULTS.append((name, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def mask_phone(number):
    digits = "".join(c for c in (number or "") if c.isdigit())
    return f"***{digits[-2:]}" if len(digits) >= 2 else "(unset)"


def _redact(value):
    text = str(value)
    return f"<id:{len(text)}ch ...{text[-2:]}>" if text else "<none>"


def smoke_telegram(timeout_s=120):
    """Poller starts BEFORE the send. We poll getUpdates ourselves (so every
    update can be logged), request allowed_updates=[callback_query, message],
    answer any accepted press immediately and edit the message to show it."""
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        return report("telegram", False, "TELEGRAM_BOT_TOKEN is unset")
    gate = check_telegram_allowed(chat_id)
    if not gate.allowed:
        return report("telegram", False, f"blocked by safety_guard: {gate.reason}")
    import telebot
    import time
    bot = telebot.TeleBot(token)
    run_id = uuid.uuid4().hex[:8]
    allowed = ["callback_query", "message"]
    try:
        hook = bot.get_webhook_info()
        print(f"  webhook set: {bool(getattr(hook, 'url', ''))} (a webhook would block getUpdates)")
        offset = None
        pending = bot.get_updates(offset=-1, timeout=0, allowed_updates=allowed)  # skip stale updates
        if pending:
            offset = pending[-1].update_id + 1
    except Exception as exc:
        return report("telegram poller start", False, f"{type(exc).__name__}: {str(exc)[:120]}")
    log, state = [], {"count": 0, "accepted": None, "msg_id": None, "has_photo": True}
    stop, ready = threading.Event(), threading.Event()

    def poll():
        nonlocal offset
        ready.set()
        while not stop.is_set():
            try:
                updates = bot.get_updates(offset=offset, timeout=5, allowed_updates=allowed)
            except Exception as exc:
                print(f"  [poll error] {type(exc).__name__}: {str(exc)[:100]}")
                stop.wait(2)
                continue
            for update in updates:
                offset = update.update_id + 1
                state["count"] += 1
                cq = update.callback_query
                if cq is None:
                    kind = "message" if update.message else "other"
                    entry = f"update#{state['count']} type={kind} accepted=no (not a callback_query)"
                else:
                    data = str(cq.data or "")
                    from_chat = getattr(getattr(getattr(cq, "message", None), "chat", None), "id", None)
                    if not data.startswith(f"smoke:{run_id}:"):
                        reason = "callback data is not from this smoke run"
                        ok = False
                    elif str(from_chat) != str(chat_id):
                        reason, ok = "press came from a chat other than the allowlisted one", False
                    else:
                        reason, ok = "matches this run and the allowlisted chat", True
                    entry = f"update#{state['count']} type=callback_query data={data.rsplit(':', 1)[-1]!r} chat={_redact(from_chat)} accepted={'yes' if ok else 'no'} ({reason})"
                    # answer immediately, for any press, so the spinner stops
                    try:
                        bot.answer_callback_query(cq.id, f"Smoke test received: {data.rsplit(':', 1)[-1]}" if ok else "Not a smoke-test button")
                    except Exception as exc:
                        entry += f" [answerCallbackQuery failed: {type(exc).__name__}]"
                    if ok and state["accepted"] is None:
                        state["accepted"] = data.rsplit(":", 1)[-1]
                        stop.set()
                        try:
                            who = getattr(cq.from_user, "first_name", None) or "operator"
                            text = f"SMOKE TEST: button press received -> {state['accepted']} from {who} at {time.strftime('%H:%M:%S')}"
                            if cq.message is not None and getattr(cq.message, "photo", None):
                                bot.edit_message_caption(text, chat_id=chat_id, message_id=cq.message.message_id, reply_markup=telebot.types.InlineKeyboardMarkup())
                            elif cq.message is not None:
                                bot.edit_message_text(text, chat_id=chat_id, message_id=cq.message.message_id, reply_markup=telebot.types.InlineKeyboardMarkup())
                        except Exception as exc:
                            entry += f" [edit failed: {type(exc).__name__}]"
                log.append(entry)
                print("  " + entry, flush=True)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    ready.wait(5)
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("Acknowledge (stops auto-call)", callback_data=f"smoke:{run_id}:acknowledge"),
               telebot.types.InlineKeyboardButton("False alarm", callback_data=f"smoke:{run_id}:false_alarm"))
    markup.row(telebot.types.InlineKeyboardButton("Escalate now", callback_data=f"smoke:{run_id}:escalate"))
    caption = ("SMOKE TEST (not a real incident)\nCamera: smoke-test\nPlace: n/a\n"
               "Press any button within 120 s to verify the callback path.")
    try:
        with open(PHOTO, "rb") as photo:
            sent = bot.send_photo(chat_id, photo, caption=caption, reply_markup=markup)
        state["msg_id"] = getattr(sent, "message_id", None)
        camera = get_camera("CAM-SAMPLE-001")
        bot.send_location(chat_id, camera.latitude, camera.longitude)
    except Exception as exc:
        stop.set()
        detail = type(exc).__name__ + (f" (HTTP {getattr(exc, 'error_code', '?')})" if hasattr(exc, "error_code") else "")
        return report("telegram send", False, detail)
    report("telegram send", True, "photo + location pin + buttons delivered")
    print(f"  SENT at {time.strftime('%H:%M:%S')}; poller running for up to {timeout_s} s ...", flush=True)
    stop.wait(timeout_s)
    stop.set()
    poller.join(8)
    print(f"  raw update count received: {state['count']}")
    if state["accepted"]:
        report("telegram callback", True, f"button press received: {state['accepted']}")
    else:
        report("telegram callback", False, f"no accepted button press in {timeout_s} s; raw updates seen: {state['count']}")
        # Leave the chat tidy: replace the caption and remove the now-dead buttons.
        try:
            if state["msg_id"]:
                bot.edit_message_caption(f"SMOKE TEST: no button press within {timeout_s} s", chat_id=chat_id,
                                         message_id=state["msg_id"], reply_markup=telebot.types.InlineKeyboardMarkup())
                print("  message edited: no-press notice, buttons removed")
        except Exception as exc:
            print(f"  [edit failed] {type(exc).__name__}")


def smoke_call_message():
    """Same text builder as a real call, fed with a fake fire at CAM-SAMPLE-001
    and the nearest cached services (no network, no discovered numbers)."""
    import json
    from api.services.notification_service import build_call_message
    camera = get_camera("CAM-SAMPLE-001")
    plan = {"assignments": []}
    try:
        cached = json.loads(settings.NEARBY_SERVICES_CACHE_PATH.read_text(encoding="utf-8")).get(camera.camera_id, {}).get("services", {})
        for cat, key in (("fire_station", "fire"), ("hospital", "hospital")):  # DISPATCH_RULES["fire"], primary first
            if cached.get(key):
                plan["assignments"].append({"service_category": cat, "status": "available",
                                            "service": min(cached[key], key=lambda x: x.get("distance_km", 1e9))})
    except Exception:
        pass
    incident = {"category": "fire", "camera_name": camera.name, "place_text": camera.place_text}
    return build_call_message(incident, plan)


def smoke_call():
    phone = settings.DEMO_PHONE_NUMBER
    gate = check_call_allowed(phone)
    if not gate.allowed:
        return report("call", False, f"blocked by safety_guard: {gate.reason}")
    api_key, agent_id = os.environ.get("OMNIDIM_API_KEY"), os.environ.get("OMNIDIM_AGENT_ID")
    if not api_key or not agent_id:
        return report("call", False, "OMNIDIM_API_KEY / OMNIDIM_AGENT_ID unset")
    import requests
    from api.services.notification_service import CALL_DISPATCH_URL
    payload = {"agent_id": int(agent_id), "to_number": phone, "call_context": {"alert_message": smoke_call_message()}}
    if os.environ.get("OMNIDIM_FROM_NUMBER_ID"):
        payload["from_number_id"] = int(os.environ["OMNIDIM_FROM_NUMBER_ID"])
    try:
        response = requests.post(CALL_DISPATCH_URL, json=payload, timeout=15,
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        response.raise_for_status()
        report("call", True, f"dispatch accepted (HTTP {response.status_code}) for number {mask_phone(phone)}; answer the phone to confirm")
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        report("call", False, f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""))


def smoke_serpapi(camera_id):
    camera = get_camera(camera_id)
    if camera is None:
        return report("serpapi", False, f"unknown camera {camera_id}")
    if not os.environ.get("SERPAPI_KEY"):
        return report("serpapi", False, "SERPAPI_KEY is unset")
    from api.services.nearby_services import NearbyServicesError, get_nearby_services
    try:
        result = get_nearby_services(camera.camera_id, camera.latitude, camera.longitude, camera.place_text, force_refresh=True)
    except NearbyServicesError as exc:
        return report("serpapi", False, str(exc)[:200])
    counts = {k: len(v) for k, v in result.get("services", {}).items()}
    ok = result.get("source") != "cache" and sum(counts.values()) > 0
    report("serpapi", ok, f"source={result.get('source')} results={counts} errors={result.get('errors') or 'none'}; "
                          f"cached at {settings.NEARBY_SERVICES_CACHE_PATH.relative_to(ROOT).as_posix()}")


def smoke_mapbox(camera_id):
    camera = get_camera(camera_id)
    if camera is None:
        return report("mapbox", False, f"unknown camera {camera_id}")
    if not os.environ.get("MAPBOX_TOKEN"):
        return report("mapbox", False, "MAPBOX_TOKEN unset (and no VITE_MAPBOX_TOKEN fallback in frontend/.env)")
    from api.services.dispatch_routing import route_to_service
    service = {"gps_coordinates": {"latitude": camera.latitude + 0.01, "longitude": camera.longitude + 0.006}}
    route = route_to_service(camera.latitude, camera.longitude, service)
    ok = route.get("route_source") == "mapbox_driving"
    report("mapbox", ok, f"route_source={route.get('route_source')} distance_km={route.get('distance_km')} "
                         f"eta_min={route.get('eta_minutes')}" + (" (cached)" if route.get("cached") else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--telegram", action="store_true", help="send one photo + location pin + buttons to TELEGRAM_CHAT_ID, wait 60 s for a press")
    parser.add_argument("--call", action="store_true", help="place ONE call to DEMO_PHONE_NUMBER only")
    parser.add_argument("--serpapi", action="store_true", help="one real nearby-services lookup (3 queries) for one camera, cached")
    parser.add_argument("--mapbox", action="store_true", help="request one Directions route")
    parser.add_argument("--camera", default="CAM-SAMPLE-001", help="camera used by --serpapi/--mapbox (default %(default)s)")
    parser.add_argument("--yes", action="store_true", help="required confirmation that you want real network traffic")
    args = parser.parse_args()
    selected = [name for name in ("telegram", "call", "serpapi", "mapbox") if getattr(args, name)]
    if not selected:
        parser.print_help()
        raise SystemExit(2)
    if not args.yes:
        raise SystemExit(f"Refusing to run {selected} without --yes (this sends real traffic to the allowlisted recipients only).")
    print(f"settings: DEMO_MODE={settings.DEMO_MODE} ALERTS_ENABLED={settings.ALERTS_ENABLED} "
          "(ALERTS_ENABLED is bypassed here: this is an explicit, allowlist-only test)")
    if args.serpapi:
        smoke_serpapi(args.camera)
    if args.mapbox:
        smoke_mapbox(args.camera)
    if args.telegram:
        smoke_telegram()
    if args.call:
        smoke_call()
    failed = [name for name, ok in RESULTS if not ok]
    print("SUMMARY:", "ALL PASS" if not failed else f"FAILED: {failed}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
