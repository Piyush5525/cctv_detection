"""Shared safety layer for EVERY outbound Telegram message or phone call
in this project -- both the new dispatch notification service
(api/services/notification_service.py) and the legacy alert functions
(Telebot_Alert.py, Call_Alert.py) route through this module before ever
reaching a real send. This is the single place the hard-block and
DEMO_MODE allowlist rules live, so neither code path can accidentally
bypass them by being wired up differently.

MANDATORY SAFETY RULES (see CHANGELOG.md "Dispatch Backend" phase):
  - A fixed set of real emergency numbers (100/101/102/108/112, India's
    police/ambulance/fire/national-emergency lines) can NEVER be dialed
    by this system, regardless of DEMO_MODE, regardless of any other
    config. This is a hard block in code, not a config value someone
    could accidentally relax.
  - In DEMO_MODE (default true), calls and Telegram messages go ONLY to
    the allowlisted demo recipients (TELEGRAM_CHAT_ID, DEMO_PHONE_NUMBER
    from env) -- never to a real hospital/police/fire number looked up
    via SerpApi, even if DEMO_MODE were somehow turned off, unless that
    exact number is also on the explicit allowlist.
  - ALERTS_ENABLED must be true for anything to be sent at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from api.core.config import settings

# Real emergency numbers (India) that must NEVER be dialed by this
# system under any configuration. Checked by normalized digits only, so
# "+91-100", "100", "+100" etc. all match -- this is intentionally
# harder to bypass than a simple string equality check.
HARD_BLOCKED_NUMBERS = frozenset({"100", "101", "102", "108", "112"})


def _normalize_number(raw: Optional[str]) -> str:
    """Strips everything except digits, then drops a leading country
    code ('91' or '+91') ONLY if the remainder still looks like a
    normal local number -- so "100" stays "100" (not mistaken for a
    truncated longer number) while "+91-9876543210" normalizes to
    "9876543210" for allowlist comparison."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    return digits


def _all_plausible_normalizations(raw: Optional[str]) -> set[str]:
    """Returns every plausible digit-only reading of `raw` that the hard
    block must check -- not just the single "best guess" normalization
    _normalize_number() uses for allowlist comparison. A real emergency
    number dialer might be handed "100", "0100", "+91100", "91-100",
    etc.; the hard block must catch the emergency code under ANY of
    these, not just the one shape _normalize_number() happens to prefer.
    This is deliberately more aggressive than allowlist matching (which
    only needs ONE canonical shape, since the allowlist itself is
    explicit) -- a false negative here (an emergency number slipping
    through) is a safety failure; a false positive (a real recipient
    number coincidentally flagged) just means it's also rejected, which
    is always safe to do by accident."""
    if not raw:
        return set()
    digits = re.sub(r"\D", "", raw)
    candidates = {digits}
    if digits.startswith("91") and len(digits) > 3:
        candidates.add(digits[2:])
    if digits.startswith("0") and len(digits) > 3:
        candidates.add(digits.lstrip("0") or digits)
    # Also check: does the raw digit string simply END with a known
    # emergency code with nothing but a plausible prefix (country code,
    # leading zero, dashes already stripped) in front of it?
    for code in HARD_BLOCKED_NUMBERS:
        if digits.endswith(code) and len(digits) - len(code) <= 3:
            candidates.add(code)
    return candidates


@dataclass
class SafetyCheckResult:
    allowed: bool
    reason: str  # human-readable, no secrets


def allowlisted_numbers() -> set[str]:
    """The only phone numbers this system may ever actually dial,
    normalized. Built fresh from env every call (not cached at import
    time) so a changed DEMO_PHONE_NUMBER env var takes effect without a
    code change -- these are not secrets themselves (a phone number),
    but the set is still kept minimal and explicit.

    IMPORTANT: this deliberately does NOT include Call_Alert.py's own
    ALERT_PHONE_NUMBER env var. An earlier version of this function
    did, on the reasoning that "it's already the only number the legacy
    path could dial" -- but once Call_Alert.py routes its OWN number
    through this exact check (which it now does), that reasoning
    becomes circular: ALERT_PHONE_NUMBER would always allowlist itself,
    regardless of what it's set to, silently defeating the entire
    check. Proven by a real test that initially passed with
    ALERT_PHONE_NUMBER set to a non-demo number before this fix. The
    ONLY numbers this system may ever dial are DEMO_PHONE_NUMBER
    (explicitly a safety-allowlist value, not reused for anything else)
    -- an operator who wants Call_Alert.py's legacy number to actually
    be reachable in DEMO_MODE must set ALERT_PHONE_NUMBER to the SAME
    value as DEMO_PHONE_NUMBER."""
    numbers = set()
    if settings.DEMO_PHONE_NUMBER:
        numbers.add(_normalize_number(settings.DEMO_PHONE_NUMBER))
    return {n for n in numbers if n}


def check_call_allowed(phone_number: Optional[str]) -> SafetyCheckResult:
    """The single gate every outbound call in this system must pass
    through, legacy or new. Returns allowed=False with a reason if the
    number is hard-blocked, not on the allowlist (DEMO_MODE or not --
    see module docstring), or simply missing."""
    if not phone_number:
        return SafetyCheckResult(False, "DEMO_PHONE_NUMBER is unset or no number provided -- call channel blocked")

    normalized = _normalize_number(phone_number)

    # Checked against EVERY plausible reading of the number (see
    # _all_plausible_normalizations' docstring), not just the single
    # canonical normalization -- the hard block must not be bypassable
    # by an unusual but still-recognizable formatting of "100" et al.
    if _all_plausible_normalizations(phone_number) & HARD_BLOCKED_NUMBERS:
        return SafetyCheckResult(False, "hard-blocked emergency number (never dialed by this system)")

    allowed_set = allowlisted_numbers()
    if normalized not in allowed_set:
        return SafetyCheckResult(False, "number is not on the allowlist (DEMO_MODE requires an explicit allowlisted recipient)")

    return SafetyCheckResult(True, "allowlisted")


def check_telegram_allowed(chat_id: Optional[str]) -> SafetyCheckResult:
    """Telegram has no real/emergency-number equivalent to hard-block,
    but DEMO_MODE still restricts sends to the configured TELEGRAM_CHAT_ID
    only -- this exists mainly so a future multi-recipient feature can't
    silently broadcast beyond the demo allowlist without updating this
    function too."""
    # Fix pass item 2: the allowlist can no longer default to the chat id it
    # is checking. The expected recipient comes from the explicit allowlist
    # or, failing that, the TELEGRAM_CHAT_ID env var; if neither is set the
    # channel is blocked (never "allow all").
    import os
    expected = settings.TELEGRAM_CHAT_ID_ALLOWLIST or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        return SafetyCheckResult(False, "TELEGRAM_CHAT_ID is unset -- telegram channel blocked")
    if not expected:
        return SafetyCheckResult(False, "no allowlisted telegram recipient configured -- telegram channel blocked")
    if str(chat_id) != str(expected):
        return SafetyCheckResult(False, "chat_id is not the allowlisted demo recipient")
    return SafetyCheckResult(True, "allowlisted")


def alerts_enabled_check() -> SafetyCheckResult:
    if not settings.ALERTS_ENABLED:
        return SafetyCheckResult(False, "ALERTS_ENABLED is false")
    return SafetyCheckResult(True, "alerts enabled")
