"""All database access (Supabase Postgres through the session pooler).

Blocking psycopg calls on a small shared pool: the backend runs them in worker threads
(asyncio.to_thread), because psycopg's async mode can't use the Windows event loop the Claude
engine needs. Every method raises RepositoryUnavailable on any database problem, so callers
handle one error type. Each statement is limited to 5 s.
"""

import json
import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 5000
POOL_MAX = 3  # the Supabase session pooler allows few connections


class RepositoryUnavailable(Exception):
    """The database couldn't be reached or the statement failed."""


class Repository:
    def __init__(self, database_url: str, schema: str = "public") -> None:
        """schema: validated by config.load_database_schema ("public" = real records, "test" = throwaway)."""
        self.schema = schema
        self._pool = ConnectionPool(
            database_url, min_size=1, max_size=POOL_MAX, timeout=5, open=False,
            kwargs={"connect_timeout": 5, "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS} -c search_path={schema}",
                    "row_factory": dict_row, "autocommit": True},
        )

    def open(self) -> None:
        self._pool.open(wait=False)

    def close(self) -> None:
        self._pool.close()

    def _run(self, sql: str, params: tuple = (), fetch: str = "none") -> Any:
        try:
            with self._pool.connection() as conn:
                cur = conn.execute(sql, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return None
        except (psycopg.Error, OSError, TimeoutError) as exc:  # the pool raises PoolTimeout (a psycopg Error)
            logger.warning("Database call failed: %s", type(exc).__name__)
            raise RepositoryUnavailable(str(exc)) from exc

    # --- conversations -------------------------------------------------------------------
    def ensure_conversation(self, cid: str, model: str | None = None, caller: dict | None = None) -> dict:
        """Creates the call's row if needed and returns it (one round trip for both)."""
        caller = caller or {}
        return self._run(
            "insert into conversations (conversation_id, model, caller_name, caller_email, caller_company, caller_identifier) "
            "values (%s, %s, %s, %s, %s, %s) on conflict (conversation_id) do update set "
            "model = coalesce(excluded.model, conversations.model), "
            "caller_name = coalesce(excluded.caller_name, conversations.caller_name), "
            "caller_email = coalesce(excluded.caller_email, conversations.caller_email), "
            "caller_company = coalesce(excluded.caller_company, conversations.caller_company), "
            "caller_identifier = coalesce(conversations.verified_customer_id, excluded.caller_email, "
            "conversations.caller_identifier, excluded.caller_identifier) returning *",
            (cid, model, caller.get("name"), caller.get("email"), caller.get("company"), caller.get("email") or "web caller"),
            "one",
        )

    def record_verification_attempt(self, cid: str, fingerprint: str) -> int:
        row = self._run("update conversations set verification_attempts = verification_attempts + 1, "
                        "last_verification_try = %s where conversation_id = %s returning verification_attempts",
                        (fingerprint, cid), "one")
        return row["verification_attempts"] if row else 1

    def mark_verified(self, cid: str, customer_id: str) -> None:
        self._run("update conversations set verified_customer_id = %s, caller_identifier = %s where conversation_id = %s",
                  (customer_id, customer_id, cid))

    def close_conversation(self, cid: str, summary: str | None) -> None:
        """Ends the record: escalated if any escalation exists, otherwise ended. Safe to call twice."""
        self._run(
            "update conversations set ended_at = coalesce(ended_at, now()), summary = coalesce(%s, summary), "
            "final_status = case when exists (select 1 from escalations e where e.conversation_id = %s) "
            "then 'escalated' else 'ended' end where conversation_id = %s",
            (summary, cid, cid),
        )

    def mark_abandoned(self, cid: str) -> None:
        self._run("update conversations set final_status = 'abandoned', ended_at = coalesce(ended_at, now()) "
                  "where conversation_id = %s and final_status = 'in_progress'", (cid,))

    # --- seed data -----------------------------------------------------------------------
    def customer_by_email(self, email: str) -> dict | None:
        return self._run("select * from customers where lower(contact_email) = %s", (email.lower(),), "one")

    def customer(self, customer_id: str) -> dict | None:
        return self._run("select * from customers where customer_id = %s", (customer_id,), "one")

    def transaction(self, transaction_id: str) -> dict | None:
        return self._run("select * from transactions where transaction_id = %s", (transaction_id,), "one")

    def payout(self, payout_id: str) -> dict | None:
        return self._run("select * from payouts where payout_id = %s", (payout_id,), "one")

    def payout_for_transaction(self, transaction_id: str) -> dict | None:
        return self._run("select * from payouts where transaction_id = %s", (transaction_id,), "one")

    # --- tickets and escalations ---------------------------------------------------------
    def ticket(self, cid: str, category: str, reference: str) -> dict | None:
        return self._run("select * from support_tickets where conversation_id = %s and category = %s and reference = %s",
                         (cid, category, reference), "one")

    def tickets(self, cid: str) -> list[dict]:
        """All of the call's tickets (at most a few): one query answers "already exists?" and the cap."""
        return self._run("select * from support_tickets where conversation_id = %s order by created_at", (cid,), "all")

    def create_ticket(self, cid: str, customer_id: str | None, category: str, priority: str, summary: str,
                      reference: str) -> tuple[str, bool]:
        """Returns (ticket_id, created). The unique key makes a repeat return the existing ticket."""
        row = self._run(
            "insert into support_tickets (conversation_id, customer_id, category, priority, summary, reference) "
            "values (%s, %s, %s, %s, %s, %s) on conflict (conversation_id, category, reference) do nothing "
            "returning ticket_id", (cid, customer_id, category, priority, summary, reference), "one")
        if row:
            return row["ticket_id"], True
        return self.ticket(cid, category, reference)["ticket_id"], False

    def escalation(self, cid: str, category: str) -> dict | None:
        return self._run("select * from escalations where conversation_id = %s and category = %s", (cid, category), "one")

    def escalations(self, cid: str) -> list[dict]:
        return self._run("select * from escalations where conversation_id = %s order by created_at", (cid,), "all")

    def create_escalation(self, values: dict, event_summary: str, event_metadata: dict) -> tuple[str, bool]:
        """Inserts the escalation and its escalation_created event in one statement: both or neither."""
        columns = list(values)
        row = self._run(
            f"with e as (insert into escalations ({', '.join(columns)}) values ({', '.join('%s' for _ in columns)}) "
            "on conflict (conversation_id, category) do nothing returning escalation_id, conversation_id), "
            "ev as (insert into conversation_events (conversation_id, event_type, summary, metadata) "
            "select conversation_id, 'escalation_created', %s, %s::jsonb || jsonb_build_object('escalation_id', escalation_id) "
            "from e) select escalation_id from e",
            (*(values[c] for c in columns), event_summary, json.dumps(event_metadata)), "one")
        if row:
            return row["escalation_id"], True
        return self.escalation(values["conversation_id"], values["category"])["escalation_id"], False

    def set_callback(self, escalation_id: str, values: dict) -> None:
        sets = ", ".join(f"{k} = %s" for k in values)
        self._run(f"update escalations set {sets}, updated_at = now() where escalation_id = %s",
                  (*values.values(), escalation_id))

    # --- logs (called in the background; failures are logged by the caller, never raised to the caller's caller)
    def log_event(self, cid: str, event_type: str, summary: str, metadata: dict | None = None) -> None:
        self._run("insert into conversation_events (conversation_id, event_type, summary, metadata) values (%s, %s, %s, %s)",
                  (cid, event_type, summary, json.dumps(metadata or {})))

    def log_tool_call(self, cid: str, tool: str, purpose: str, input_summary: str, result_summary: str,
                      status: str, error: str | None, duration_ms: int) -> None:
        self._run("insert into tool_calls (conversation_id, tool_name, purpose, input_summary, result_summary, status, "
                  "error_message, duration_ms) values (%s, %s, %s, %s, %s, %s, %s, %s)",
                  (cid, tool, purpose, input_summary, result_summary, status, error, duration_ms))

    def log_retrieval(self, cid: str, query: str, chunk_ids: list, titles: list, scores: list, summaries: list,
                      duration_ms: float) -> None:
        self._run("insert into retrieval_logs (conversation_id, query, chunk_ids, titles, scores, summaries, duration_ms) "
                  "values (%s, %s, %s, %s, %s, %s, %s)", (cid, query, chunk_ids, titles, scores, summaries, duration_ms))

    def log_turn(self, cid: str, user_transcript: str, assistant_response: str, answer_type: str,
                 confidence_note: str, first_text_ms: float | None, total_ms: float) -> None:
        self._run("insert into conversation_turns (conversation_id, user_transcript, assistant_response, answer_type, "
                  "confidence_note, first_text_ms, total_ms) values (%s, %s, %s, %s, %s, %s, %s)",
                  (cid, user_transcript, assistant_response, answer_type, confidence_note,
                   int(first_text_ms) if first_text_ms is not None else None, int(total_ms)))
