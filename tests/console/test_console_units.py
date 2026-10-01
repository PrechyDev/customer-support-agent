from datetime import UTC, date, datetime, timedelta

from customer_support_agent.api.ratelimit import RateLimiter
from customer_support_agent.console import permissions as perms
from customer_support_agent.console import security, views


def test_passwords_are_hashed_salted_and_checked():
    stored = security.hash_password("a-long-passphrase")
    assert stored.startswith("scrypt$") and "a-long-passphrase" not in stored
    assert stored != security.hash_password("a-long-passphrase")  # a new salt every time
    assert security.verify_password("a-long-passphrase", stored)
    assert not security.verify_password("wrong", stored) and not security.verify_password("x", None)


def test_session_cookies_can_not_be_forged_or_reused_after_expiry():
    cookie = security.sign_session("k" * 32, "member-1", 2, now=1000)
    assert security.read_session("k" * 32, cookie, now=1001) == ("member-1", 2)
    assert security.read_session("j" * 32, cookie, now=1001) is None  # another key
    assert security.read_session("k" * 32, cookie.replace(".", "x."), now=1001) is None  # tampered
    assert security.read_session("k" * 32, cookie, now=1000 + security.SESSION_SECONDS + 1) is None  # expired
    token, digest = security.new_link_token()
    assert len(token) >= 40 and digest == security.token_hash(token) and token not in digest


def test_new_password_rules():
    assert security.check_new_password("Ada Obi", "a-long-passphrase", "a-long-passphrase", "ada@x.com") == {}
    problems = security.check_new_password("A", "short", "other", "ada@x.com")
    assert set(problems) == {"name", "password", "confirm_password"}
    assert "password" in security.check_new_password("Ada", "ada@x.com", "ada@x.com", "ada@x.com")
    assert security.normalise_email(" Ada@X.com ") == "ada@x.com" and security.normalise_email("nope") is None


def test_roles():
    assert perms.can_invite("superadmin", "admin") and perms.can_invite("admin", "support")
    assert not perms.can_invite("admin", "admin") and not perms.can_invite("support", "support")
    assert not perms.can_invite("superadmin", "superadmin")
    assert not perms.can_manage("superadmin", "superadmin") and not perms.can_manage("admin", "admin")
    assert perms.can_change_role("superadmin", "support", "admin") and not perms.can_change_role("admin", "support", "admin")
    assert perms.can_resolve("support", "me", "me") and not perms.can_resolve("support", "me", "you")
    assert perms.can_resolve("admin", "me", None)


def test_outcomes_and_analytics():
    base = {"has_escalation": False, "has_ticket": False, "has_decline": False, "final_status": "ended"}
    assert views.outcome({**base, "has_escalation": True, "has_ticket": True}) == "handed_to_specialist"
    assert views.outcome({**base, "final_status": "abandoned"}) == "caller_hung_up"
    assert views.outcome({**base, "has_decline": True}) == "could_not_answer" and views.outcome(base) == "answered"

    start = datetime(2026, 10, 1, 10, tzinfo=UTC)
    rows = [{**base, "started_at": start, "ended_at": start + timedelta(seconds=120), "rating": "yes"},
            {**base, "has_escalation": True, "started_at": start, "ended_at": start + timedelta(seconds=60),
             "rating": None}]
    report = views.analytics(rows, previous_count=1, declined=[{"user_transcript": "Do you have a mobile app?"}] * 2,
                             start=date(2026, 9, 29), end=date(2026, 10, 1))
    assert report["kpis"] == {"conversations": 2, "conversations_change_pct": 100, "answered_by_assistant_pct": 50,
                              "handed_to_specialist_pct": 50, "rated_helpful_pct": 100, "average_duration_s": 90}
    assert [p["count"] for p in report["series"]["points"]] == [0, 0, 2]
    assert report["unanswered"] == [{"question": "Do you have a mobile app?", "times": 2}]


def test_rate_limiter_window():
    clock = [0.0]
    limiter = RateLimiter(limit=2, window_seconds=10, clock=lambda: clock[0])
    assert not limiter.hit("a") and not limiter.hit("a") and limiter.hit("a")
    clock[0] = 11
    assert not limiter.blocked("a")  # the window moved on
