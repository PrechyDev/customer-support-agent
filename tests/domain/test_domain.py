from datetime import UTC, date, datetime

import pytest

from customer_support_agent.domain.callbacks import CallbackError, callback_window
from customer_support_agent.domain.normalise import mask_email, normalise_company, normalise_email, parse_reference
from customer_support_agent.domain.status import caller_status

TODAY = date(2026, 10, 1)  # a Thursday


def test_spoken_input_is_normalised():
    assert normalise_email("Amara at Lagos Ledger dot example") == "amara@lagosledger.example"
    assert normalise_email("not an email") is None
    assert normalise_company("Lagos Ledger") == normalise_company("LagosLedger") == "lagosledger"
    assert parse_reference("T X N nine zero zero one") == "TXN-9001"
    assert parse_reference("payout 7002", default_prefix="TXN") == "PAY-7002"
    assert parse_reference("9001", default_prefix="PAY") == "PAY-9001"
    assert parse_reference("txn 90") is None
    assert mask_email("amara@lagosledger.example") == "a***@lagosledger.example"


def test_status_first_then_date():
    cases = [  # (kind, stored, due, expected status, next step)
        ("transaction", "processing", date(2026, 8, 19), "delayed", "escalate"),  # TXN-9001: date passed
        ("transaction", "processing", date(2026, 10, 5), "processing", "none"),
        ("transaction", "failed", None, "failed", "ticket"),
        ("payout", "failed", date(2026, 8, 15), "failed", "escalate"),  # PAY-7003: date ignored
        ("payout", "review required", date(2026, 8, 16), "under review", "escalate"),
        ("transaction", "completed", date(2026, 8, 15), "completed", "none"),
        ("payout", "lost", None, "unknown", "escalate"),
    ]
    for kind, stored, due, status, step in cases:
        result = caller_status(kind, stored, due, TODAY)
        assert (result.status, result.next_step) == (status, step), (kind, stored)


NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # Thursday 09:00 UTC = 10:00 in Lagos


def test_callback_window_in_local_time_trimmed_to_support_hours():
    w = callback_window("Lagos", "tomorrow", "afternoon", NOW)  # Fri 12-17 Lagos = 11-16 UTC: inside hours
    assert (w.start_utc.hour, w.end_utc.hour, w.timezone) == (11, 16, "Africa/Lagos")
    assert w.spoken == "Friday 2 October, between 12pm and 5pm Lagos time"
    evening = callback_window("Nigeria", "today", "5pm", NOW)  # 17-19 Lagos = 16-18 UTC: kept
    assert (evening.start_utc.hour, evening.end_utc.hour) == (16, 18)
    assert callback_window("Lagos", "tomorrow", "any time", NOW) is None


def test_daylight_saving_is_handled():
    winter = callback_window("New York", "2026-12-01", "9am", datetime(2026, 11, 30, 12, tzinfo=UTC))
    summer = callback_window("New York", "2026-10-02", "9am", NOW)
    assert (winter.start_utc.hour, summer.start_utc.hour) == (14, 13)  # UTC-5 in winter, UTC-4 in summer


def test_impossible_windows_give_a_hint_the_agent_can_say():
    with pytest.raises(CallbackError) as weekend:
        callback_window("Lagos", "saturday", "morning", NOW)
    assert weekend.value.code == "outside_hours" and "weekdays 9am to 7pm Lagos time" in weekend.value.hint
    for place, day, when, code in [("Ikeja", "tomorrow", "morning", "unknown_timezone"),
                                   ("Lagos", "2026-09-01", "morning", "invalid_input"),
                                   ("Lagos", "tomorrow", "half past never", "invalid_input")]:
        with pytest.raises(CallbackError) as exc:
            callback_window(place, day, when, NOW)
        assert exc.value.code == code
