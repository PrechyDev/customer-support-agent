"""Read one call's records back as a timeline: `poetry run relaypay-call`.

    poetry run relaypay-call                 latest call, in DATABASE_SCHEMA (from .env)
    poetry run relaypay-call --schema test   latest call in the test schema
    poetry run relaypay-call --call <id>     one call by its Vapi call ID
    poetry run relaypay-call --list          the 10 most recent calls

Shows the conversation row, then every turn, tool call, search and event in time order (seconds
from the call start), then the tickets and escalations. Read-only. Emails are masked.
"""

import argparse
import logging
import sys

import psycopg
from dotenv import find_dotenv, load_dotenv
from psycopg.rows import dict_row

from customer_support_agent.config import ConfigError, load_database_schema, load_database_url
from customer_support_agent.domain.normalise import mask_email

logger = logging.getLogger(__name__)

_TIMELINE = (
    ("turn", "select created_at, user_transcript, assistant_response, answer_type, confidence_note, first_text_ms, "
             "total_ms from conversation_turns where conversation_id = %s"),
    ("tool", "select created_at, tool_name, input_summary, result_summary, status, error_message, duration_ms "
             "from tool_calls where conversation_id = %s"),
    ("search", "select created_at, query, chunk_ids, scores, duration_ms from retrieval_logs where conversation_id = %s"),
    ("event", "select created_at, event_type, summary from conversation_events where conversation_id = %s"),
)


def _describe(kind: str, r: dict) -> str:
    if kind == "turn":
        return (f"TURN  [{r['answer_type']}] first text {r['first_text_ms']} ms, total {r['total_ms']} ms\n"
                f"        caller: {r['user_transcript']}\n        bex:    {r['assistant_response']}\n"
                f"        note:   {r['confidence_note']}")
    if kind == "tool":
        error = f" error={r['error_message']}" if r["error_message"] else ""
        return (f"TOOL  {r['tool_name']} ({r['status']}, {r['duration_ms']} ms){error}\n"
                f"        in:  {r['input_summary']}\n        out: {r['result_summary']}")
    if kind == "search":
        found = ", ".join(f"{c} ({s})" for c, s in zip(r["chunk_ids"], r["scores"])) or "nothing"
        return f"SEARCH \"{r['query']}\" ({r['duration_ms']:.1f} ms) -> {found}"
    return f"EVENT {r['event_type']}: {r['summary']}"


def show_call(conn: psycopg.Connection, cid: str) -> None:
    conv = conn.execute("select * from conversations where conversation_id = %s", (cid,)).fetchone()
    if conv is None:
        print(f"No conversation {cid} in this schema.")
        return
    start = conv["started_at"]
    print(f"CALL {cid}\n  started {start:%Y-%m-%d %H:%M:%S} UTC, ended {conv['ended_at'] or '-'}, "
          f"status {conv['final_status']}, model {conv['model']}")
    print(f"  form: name={conv['caller_name']!r} email={mask_email(conv['caller_email'])} "
          f"company={conv['caller_company']!r}")
    print(f"  verified={conv['verified_customer_id']} attempts={conv['verification_attempts']}")
    print(f"  Vapi summary: {conv['summary'] or '-'}\n")

    items = [(r["created_at"], kind, r) for kind, sql in _TIMELINE for r in conn.execute(sql, (cid,)).fetchall()]
    for at, kind, r in sorted(items, key=lambda item: item[0]):
        print(f"+{(at - start).total_seconds():6.1f}s  {_describe(kind, r)}")

    for t in conn.execute("select * from support_tickets where conversation_id = %s", (cid,)).fetchall():
        print(f"\nTICKET {t['ticket_id']} {t['category']}/{t['priority']} ref={t['reference'] or '-'} "
              f"customer={t['customer_id']} status={t['status']}: {t['summary']}")
    for e in conn.execute("select * from escalations where conversation_id = %s", (cid,)).fetchall():
        print(f"ESCALATION {e['escalation_id']} -> {e['ticket_id']} {e['category']} verified={e['verified']} "
              f"contact={e['user_name']} {mask_email(e['user_email'])} callback={e['preferred_time_raw'] or '-'} "
              f"({e['callback_timezone'] or 'no window'}): {e['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Show one call's records from Supabase.")
    parser.add_argument("--call", help="Vapi call ID (default: the latest call)")
    parser.add_argument("--schema", help="public or test (default: DATABASE_SCHEMA from .env)")
    parser.add_argument("--list", action="store_true", help="list the 10 most recent calls")
    args = parser.parse_args()

    load_dotenv(find_dotenv(usecwd=True))
    try:
        url = load_database_url()
        schema = load_database_schema({"DATABASE_SCHEMA": args.schema} if args.schema else None)
    except ConfigError as exc:
        print(f"Can't read calls: {exc}")
        return 2
    try:
        with psycopg.connect(url, connect_timeout=10, row_factory=dict_row) as conn:
            conn.execute(f"set search_path to {schema}")  # validated name
            print(f"(schema: {schema})\n")
            if args.list:
                for c in conn.execute("select conversation_id, started_at, final_status from conversations "
                                      "order by started_at desc limit 10").fetchall():
                    print(f"{c['started_at']:%Y-%m-%d %H:%M:%S}  {c['final_status']:<12} {c['conversation_id']}")
                return 0
            cid = args.call or (conn.execute("select conversation_id from conversations order by started_at desc "
                                             "limit 1").fetchone() or {}).get("conversation_id")
            if not cid:
                print("No calls recorded in this schema yet.")
                return 0
            show_call(conn, cid)
    except psycopg.Error as exc:
        print(f"Database error: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
