"""Callback windows (SPECS §6): the caller's words, in their time zone, trimmed to support hours.

Support hours (an assumption to confirm with RelayPay): Monday to Friday, 08:00-18:00 UTC, no holidays.
All time maths happens here with zoneinfo (which knows daylight saving), never in the model.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

UTC = ZoneInfo("UTC")
SUPPORT_START, SUPPORT_END = time(8), time(18)  # UTC, Monday to Friday
MAX_DAYS_AHEAD = 14
EXACT_TIME_HOURS = 2  # "3pm" becomes 3-5pm
_PARTS = {"morning": (time(9), time(12)), "afternoon": (time(12), time(17)), "evening": (time(17), time(20))}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# Countries RelayPay serves (and a few common abbreviations) -> a representative zone
_PLACES = {
    "nigeria": "Africa/Lagos", "wat": "Africa/Lagos", "kenya": "Africa/Nairobi", "eat": "Africa/Nairobi",
    "ghana": "Africa/Accra", "gmt": "Africa/Accra", "rwanda": "Africa/Kigali", "cat": "Africa/Maputo",
    "south africa": "Africa/Johannesburg", "sast": "Africa/Johannesburg", "uk": "Europe/London",
    "united kingdom": "Europe/London", "london": "Europe/London", "bst": "Europe/London", "cet": "Europe/Paris",
    "utc": "UTC", "est": "America/New_York", "edt": "America/New_York", "cst": "America/Chicago",
    "pst": "America/Los_Angeles", "usa": "America/New_York", "canada": "America/Toronto",
    # Spoken time zone names ("West African Time" -> "west african" after dropping "time")
    "west africa": "Africa/Lagos", "west african": "Africa/Lagos", "east africa": "Africa/Nairobi",
    "east african": "Africa/Nairobi", "central africa": "Africa/Maputo", "central african": "Africa/Maputo",
    "south african": "Africa/Johannesburg", "greenwich mean": "UTC", "british": "Europe/London",
    "british summer": "Europe/London", "central european": "Europe/Paris", "eastern": "America/New_York",
    "central": "America/Chicago", "pacific": "America/Los_Angeles",
}
_NUMBER_WORDS = {w: str(i) for i, w in enumerate(("zero one two three four five six seven eight nine ten "
                                                   "eleven twelve").split())}
_SUFFIX = re.compile(r"\s+(?:standard\s+)?(?:summer\s+)?time(?:\s+zone)?$|\s+zone$")
_OFFSET = re.compile(r"^(?:utc|gmt)\s*(plus|minus|\+|-)\s*(\d{1,2})$")


# Calling codes for the zones above, so a local number ("0814 346 3800") needs no country code.
_CALLING_CODES = {
    "Africa/Lagos": "234", "Africa/Accra": "233", "Africa/Nairobi": "254", "Africa/Kigali": "250",
    "Africa/Johannesburg": "27", "Africa/Maputo": "258", "Africa/Kampala": "256", "Africa/Dar_es_Salaam": "255",
    "Europe/London": "44", "Europe/Paris": "33", "Europe/Berlin": "49", "Europe/Amsterdam": "31",
}


def calling_code(zone_key: str | None) -> str | None:
    """'Africa/Lagos' -> '234'. None when the zone doesn't tell us the country (e.g. 'UTC+1')."""
    if not zone_key:
        return None
    if zone_key.startswith("America/") and zone_key in ("America/New_York", "America/Chicago", "America/Denver",
                                                        "America/Los_Angeles", "America/Toronto"):
        return "1"
    return _CALLING_CODES.get(zone_key)


class CallbackError(ValueError):
    def __init__(self, code: str, hint: str) -> None:
        super().__init__(hint)
        self.code, self.hint = code, hint


@dataclass(frozen=True)
class CallbackWindow:
    start_utc: datetime
    end_utc: datetime
    timezone: str
    spoken: str  # "Thursday 2 October, between 1pm and 5pm Lagos time"


@lru_cache(maxsize=1)
def _zones_by_city() -> dict[str, str]:
    return {z.rsplit("/", 1)[-1].lower().replace("_", " "): z for z in available_timezones() if "/" in z}


def resolve_timezone(place: str | None) -> ZoneInfo:
    key = " ".join((place or "").lower().replace(",", " ").split())
    if not key:
        raise CallbackError("unknown_timezone", "Ask which city or time zone the caller is in.")
    try:
        if "/" in key or key == "utc":
            return ZoneInfo(place.strip() if "/" in key else "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        pass
    key = _SUFFIX.sub("", key).strip()
    key = " ".join(_NUMBER_WORDS.get(w, w) for w in key.split())  # "gmt plus one" -> "gmt plus 1"
    offset = _OFFSET.match(key)
    if offset:  # "UTC+1", "GMT plus one": a fixed offset (Etc zones have the sign reversed)
        hours = int(offset.group(2))
        if hours > 14:
            raise CallbackError("unknown_timezone", "Ask for a nearby city or their time zone.")
        sign = "-" if offset.group(1) in ("plus", "+") else "+"
        return ZoneInfo("UTC" if hours == 0 else f"Etc/GMT{sign}{hours}")
    name = _PLACES.get(key) or _zones_by_city().get(key)
    if name is None:
        raise CallbackError("unknown_timezone", f"'{place}' isn't a place or time zone I recognise. Ask for a nearby "
                                                f"city or their time zone (either is fine, e.g. a UTC offset).")
    return ZoneInfo(name)


def _day(word: str, today: date) -> date:
    word = (word or "").strip().lower()
    if word in ("", "today"):
        return today
    if word == "tomorrow":
        return today + timedelta(days=1)
    if word in _WEEKDAYS:  # the next such day, today included
        return today + timedelta(days=(_WEEKDAYS.index(word) - today.weekday()) % 7)
    try:
        return date.fromisoformat(word)
    except ValueError:
        raise CallbackError("invalid_input", "Ask which day suits them (today, tomorrow, a weekday, or a date).") from None


def _hours(word: str) -> tuple[time, time] | None:
    word = (word or "").strip().lower()
    if word in ("", "any", "anytime", "any time"):
        return None
    if word in _PARTS:
        return _PARTS[word]
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", word.replace(".", ""))
    if not match:
        raise CallbackError("invalid_input", "Ask for a time, or morning, afternoon or evening.")
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if match.group(3) == "pm" and hour < 12:
        hour += 12
    if match.group(3) == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise CallbackError("invalid_input", "Ask for a valid time.")
    start = datetime.combine(date.min, time(hour, minute))
    return start.time(), min(start + timedelta(hours=EXACT_TIME_HOURS), datetime.combine(date.min, time(23, 59))).time()


def _clock(moment: datetime) -> str:
    text = moment.strftime("%I:%M%p").lstrip("0").lower().replace(":00", "")
    return text


def support_hours_spoken(zone: ZoneInfo, on: date) -> str:
    start = datetime.combine(on, SUPPORT_START, UTC).astimezone(zone)
    end = datetime.combine(on, SUPPORT_END, UTC).astimezone(zone)
    return f"weekdays {_clock(start)} to {_clock(end)} {_city(zone)} time"


def _city(zone: ZoneInfo) -> str:
    if zone.key == "UTC":
        return "UTC"
    if zone.key.startswith("Etc/GMT"):  # the caller gave an offset: say it back the way they said it
        hours = zone.key[len("Etc/GMT"):]
        return f"UTC{'+' if hours.startswith('-') else '-'}{hours.lstrip('+-')}"
    return zone.key.rsplit("/", 1)[-1].replace("_", " ")


def callback_window(place: str | None, day: str, when: str, now_utc: datetime) -> CallbackWindow | None:
    """None means "any time" (no window). Raises CallbackError with a hint the agent can say."""
    zone = resolve_timezone(place)
    local_today = now_utc.astimezone(zone).date()
    local_day = _day(day, local_today)
    if local_day < local_today or (local_day - local_today).days > MAX_DAYS_AHEAD:
        raise CallbackError("invalid_input", f"Ask for a day in the next {MAX_DAYS_AHEAD} days.")
    hours = _hours(when)
    if hours is None:
        return None

    start = datetime.combine(local_day, hours[0], zone).astimezone(UTC)
    end = datetime.combine(local_day, hours[1], zone).astimezone(UTC)
    start = max(start, now_utc)  # never a window in the past
    # Trim to support hours on the UTC day(s) the window touches.
    best: tuple[datetime, datetime] | None = None
    for offset in (-1, 0, 1):
        d = start.date() + timedelta(days=offset)
        if d.weekday() >= 5:
            continue
        lo, hi = max(start, datetime.combine(d, SUPPORT_START, UTC)), min(end, datetime.combine(d, SUPPORT_END, UTC))
        if lo < hi and (best is None or (hi - lo) > (best[1] - best[0])):
            best = (lo, hi)
    if best is None:
        raise CallbackError("outside_hours", f"Specialists are available {support_hours_spoken(zone, local_day)}. Offer a time in those hours.")

    lo_local, hi_local = best[0].astimezone(zone), best[1].astimezone(zone)
    spoken = f"{lo_local:%A} {lo_local.day} {lo_local:%B}, between {_clock(lo_local)} and {_clock(hi_local)} {_city(zone)} time"
    return CallbackWindow(start_utc=best[0], end_utc=best[1], timezone=zone.key, spoken=spoken)


def spoken_window(start_utc: datetime, end_utc: datetime, timezone: str) -> str:
    """A stored callback window as the caller hears it: "Friday 2 October, between 10am and 12pm Lagos time".
    Same wording as CallbackWindow.spoken. Raises CallbackError for an unknown time zone."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise CallbackError("unknown_timezone", f"Unknown stored time zone '{timezone}'.") from None
    lo, hi = start_utc.astimezone(zone), end_utc.astimezone(zone)
    return f"{lo:%A} {lo.day} {lo:%B}, between {_clock(lo)} and {_clock(hi)} {_city(zone)} time"
