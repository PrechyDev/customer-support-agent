"""The support console's SQL (docs/CONSOLE_API.md). Blocking calls on the shared Repository pool; the API runs
them in worker threads. Table and column names come from fixed maps, never from input; values are parameters.
"""

from datetime import datetime
from typing import Any

from customer_support_agent.db.repository import Repository

CASE_TABLES = {"ticket": ("support_tickets", "ticket_id"), "escalation": ("escalations", "escalation_id")}
ONLY_IF = {"unowned_open": "owner_id is null and status <> 'closed'", "not_closed": "status <> 'closed'",
           "closed": "status = 'closed'"}

_MEMBER_COLUMNS = (
    "m.member_id::text as member_id, m.email, m.name, m.role, m.status, m.created_at, m.activated_at, "
    "m.last_login_at, m.session_version, m.password_hash, m.invite_kind, m.invite_expires_at, "
    "inviter.name as invited_by_name"
)
_MEMBER_FROM = "team_members m left join team_members inviter on inviter.member_id = m.invited_by"

# Every case as one row: escalations, plus tickets that have no escalation (so nothing is listed twice).
_CASES = """
select 'escalation' as case_type, e.escalation_id as case_id, e.reason as title, e.category,
       coalesce(t.priority, 'high') as priority, e.status, e.owner_id::text as owner_id, o.name as owner_name,
       coalesce(e.customer_id, t.customer_id) as customer_id, cu.company_name as company,
       coalesce(t.reference, '') as reference, e.call_booked, e.callback_start_utc, e.callback_end_utc,
       e.callback_timezone, e.contact_method, e.created_at, e.resolved_at, e.conversation_id, e.ticket_id
from escalations e
left join support_tickets t on t.ticket_id = e.ticket_id
left join customers cu on cu.customer_id = coalesce(e.customer_id, t.customer_id)
left join team_members o on o.member_id = e.owner_id
union all
select 'ticket', t.ticket_id, t.summary, t.category, t.priority, t.status, t.owner_id::text, o.name,
       t.customer_id, cu.company_name, t.reference, false, null, null, null, null, t.created_at, t.resolved_at,
       t.conversation_id, t.ticket_id
from support_tickets t
left join customers cu on cu.customer_id = t.customer_id
left join team_members o on o.member_id = t.owner_id
where not exists (select 1 from escalations e where e.ticket_id = t.ticket_id)
"""

_CONVERSATIONS = """
select c.conversation_id, c.started_at, c.ended_at, c.final_status, c.summary, c.rating, c.channel, c.caller_name,
       c.caller_email, c.verified_customer_id, cu.company_name,
       exists (select 1 from escalations e where e.conversation_id = c.conversation_id) as has_escalation,
       exists (select 1 from support_tickets t where t.conversation_id = c.conversation_id) as has_ticket,
       exists (select 1 from conversation_turns tu where tu.conversation_id = c.conversation_id
               and tu.answer_type = 'decline') as has_decline
from conversations c left join customers cu on cu.customer_id = c.verified_customer_id
"""


class ConsoleStore:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def _run(self, sql: str, params: tuple = (), fetch: str = "none") -> Any:
        return self._repo._run(sql, params, fetch)

    # --- team members ----------------------------------------------------------------------
    def member(self, member_id: str) -> dict | None:
        return self._run(f"select {_MEMBER_COLUMNS} from {_MEMBER_FROM} where m.member_id::text = %s",
                         (member_id,), "one")

    def member_by_email(self, email: str) -> dict | None:
        return self._run(f"select {_MEMBER_COLUMNS} from {_MEMBER_FROM} where m.email = %s", (email,), "one")

    def member_by_token(self, token_hash: str) -> dict | None:
        """A pending invite or reset whose link hasn't expired or been used."""
        return self._run(f"select {_MEMBER_COLUMNS} from {_MEMBER_FROM} where m.invite_token_hash = %s "
                         "and m.invite_expires_at > now() and m.status <> 'disabled'", (token_hash,), "one")

    def members(self) -> list[dict]:
        return self._run(f"select {_MEMBER_COLUMNS} from {_MEMBER_FROM} order by (m.role = 'superadmin') desc, "
                         "coalesce(m.name, m.email)", (), "all")

    def create_member(self, email: str, role: str, invited_by: str | None, token_hash: str, kind: str,
                      expires_at: datetime) -> str | None:
        """The new member's ID, or None if the email is already a member."""
        row = self._run("insert into team_members (email, role, invited_by, invite_token_hash, invite_kind, "
                        "invite_expires_at) values (%s, %s, %s, %s, %s, %s) on conflict (email) do nothing "
                        "returning member_id::text as member_id",
                        (email, role, invited_by, token_hash, kind, expires_at), "one")
        return row["member_id"] if row else None

    def set_link(self, member_id: str, token_hash: str, kind: str, expires_at: datetime) -> None:
        self._run("update team_members set invite_token_hash = %s, invite_kind = %s, invite_expires_at = %s "
                  "where member_id::text = %s", (token_hash, kind, expires_at, member_id))

    def accept_link(self, member_id: str, name: str, password_hash: str) -> None:
        """Sets the name and password, uses up the link, activates, and signs out any older sessions."""
        self._run("update team_members set name = %s, password_hash = %s, status = 'active', "
                  "invite_token_hash = null, invite_kind = null, invite_expires_at = null, "
                  "activated_at = coalesce(activated_at, now()), session_version = session_version + 1 "
                  "where member_id::text = %s", (name, password_hash, member_id))

    def set_status(self, member_id: str, status: str) -> None:
        self._run("update team_members set status = %s, session_version = session_version + "
                  "case when %s = 'disabled' then 1 else 0 end where member_id::text = %s",
                  (status, status, member_id))

    def set_role(self, member_id: str, role: str) -> None:
        self._run("update team_members set role = %s where member_id::text = %s", (role, member_id))

    def touch_login(self, member_id: str) -> None:
        self._run("update team_members set last_login_at = now() where member_id::text = %s", (member_id,))

    # --- cases -----------------------------------------------------------------------------
    def cases(self, case_type: str | None = None, status: str | None = None, owner_id: str | None = None,
              unassigned: bool = False, created_after: datetime | None = None, conversation_id: str | None = None,
              customer_id: str | None = None, limit: int = 200) -> list[dict]:
        where: list[str] = []
        params: list[Any] = []
        if case_type:
            where.append("case_type = %s"), params.append(case_type)
        if status == "open":
            where.append("status <> 'closed'")
        elif status == "closed":
            where.append("status = 'closed'")
        if owner_id:
            where.append("owner_id = %s"), params.append(owner_id)
        if unassigned:
            where.append("owner_id is null")
        if created_after:
            where.append("created_at > %s"), params.append(created_after)
        if conversation_id:
            where.append("conversation_id = %s"), params.append(conversation_id)
        if customer_id:
            where.append("customer_id = %s"), params.append(customer_id)
        sql = f"select * from ({_CASES}) cases" + (f" where {' and '.join(where)}" if where else "")
        return self._run(sql + " order by created_at desc limit %s", (*params, limit), "all")

    def case(self, case_type: str, case_id: str) -> dict | None:
        rows = self._run(f"select * from ({_CASES}) cases where case_type = %s and case_id = %s",
                         (case_type, case_id), "all")
        return rows[0] if rows else None

    def case_extra(self, case_type: str, case_id: str) -> dict | None:
        if case_type == "escalation":
            return self._run("select e.reason, t.summary, e.user_name, e.user_email, e.callback_phone, e.verified, "
                             "e.preferred_time_raw, e.resolution_note from escalations e left join support_tickets t "
                             "on t.ticket_id = e.ticket_id where e.escalation_id = %s", (case_id,), "one")
        return self._run("select summary, summary as reason, resolution_note from support_tickets where ticket_id = %s",
                         (case_id,), "one")

    def update_case(self, case_type: str, case_id: str, *, owner_id: str | None = None, status: str | None = None,
                    resolution_note: str | None = None, reopen: bool = False, only_if: str | None = None) -> bool:
        """only_if: a state the case must still be in (ONLY_IF), checked in the same statement, so two staff
        acting at once can't both succeed. False if no row matched."""
        table, key = CASE_TABLES[case_type]
        sets, params = ["updated_at = now()"], []
        if owner_id is not None:
            sets.append("owner_id = %s"), params.append(owner_id)
        if status:
            sets.append("status = %s"), params.append(status)
        if resolution_note is not None:
            sets += ["resolution_note = %s", "resolved_at = now()"]
            params.append(resolution_note)
        if reopen:
            sets.append("resolved_at = null")
        condition = f" and {ONLY_IF[only_if]}" if only_if else ""
        row = self._run(f"update {table} set {', '.join(sets)} where {key} = %s{condition} returning {key}",
                        (*params, case_id), "one")
        return row is not None

    def add_case_event(self, case_type: str, case_id: str, member_id: str | None, kind: str, text: str) -> dict:
        return self._run("insert into case_events (case_type, case_id, member_id, kind, text) values "
                         "(%s, %s, %s, %s, %s) returning created_at", (case_type, case_id, member_id, kind, text), "one")

    def case_events(self, case_type: str, case_id: str) -> list[dict]:
        return self._run("select ev.created_at, ev.kind, ev.text, m.name as who from case_events ev left join "
                         "team_members m on m.member_id = ev.member_id where ev.case_type = %s and ev.case_id = %s "
                         "order by ev.created_at", (case_type, case_id), "all")

    # --- conversations ---------------------------------------------------------------------
    def conversations(self, search: str | None = None, started_from: datetime | None = None,
                      started_to: datetime | None = None, customer_id: str | None = None,
                      limit: int = 200) -> list[dict]:
        where, params = [], []
        if search:
            like = f"%{search}%"
            where.append("(c.caller_name ilike %s or c.summary ilike %s or cu.company_name ilike %s "
                         "or c.conversation_id ilike %s)")
            params += [like] * 4
        if started_from:
            where.append("c.started_at >= %s"), params.append(started_from)
        if started_to:
            where.append("c.started_at < %s"), params.append(started_to)
        if customer_id:
            where.append("(c.verified_customer_id = %s or exists (select 1 from support_tickets t where "
                         "t.conversation_id = c.conversation_id and t.customer_id = %s))")
            params += [customer_id, customer_id]
        sql = _CONVERSATIONS + (f" where {' and '.join(where)}" if where else "")
        return self._run(sql + " order by c.started_at desc limit %s", (*params, limit), "all")

    def conversation(self, cid: str) -> dict | None:
        return self._run(_CONVERSATIONS + " where c.conversation_id = %s", (cid,), "one")

    def turns(self, cid: str) -> list[dict]:
        return self._run("select created_at, user_transcript, assistant_response, answer_type, confidence_note "
                         "from conversation_turns where conversation_id = %s order by created_at", (cid,), "all")

    def tool_calls(self, cid: str) -> list[dict]:
        return self._run("select created_at, tool_name, input_summary, result_summary, status from tool_calls "
                         "where conversation_id = %s order by created_at", (cid,), "all")

    def searches(self, cid: str) -> list[dict]:
        return self._run("select query, chunk_ids, titles from retrieval_logs where conversation_id = %s "
                         "order by created_at", (cid,), "all")

    def declined_questions(self, started_from: datetime, started_to: datetime) -> list[dict]:
        return self._run("select tu.user_transcript from conversation_turns tu join conversations c on "
                         "c.conversation_id = tu.conversation_id where tu.answer_type = 'decline' and "
                         "c.started_at >= %s and c.started_at < %s", (started_from, started_to), "all")

    # --- customers -------------------------------------------------------------------------
    def customers(self, search: str | None = None) -> list[dict]:
        sql = ("select cu.customer_id, cu.company_name as company, cu.contact_name, cu.contact_email, cu.plan, "
               "cu.account_status, cu.region, "
               "(select count(*) from support_tickets t where t.customer_id = cu.customer_id and t.status <> 'closed') "
               "as open_cases, "
               "(select count(*) from conversations c where c.verified_customer_id = cu.customer_id) as calls "
               "from customers cu")
        if search:
            like = f"%{search}%"
            return self._run(sql + " where cu.company_name ilike %s or cu.contact_name ilike %s or cu.customer_id "
                             "ilike %s or cu.contact_email ilike %s order by cu.company_name",
                             (like, like, like, like), "all")
        return self._run(sql + " order by cu.company_name", (), "all")

    def customer(self, customer_id: str) -> dict | None:
        return self._run("select * from customers where customer_id = %s", (customer_id,), "one")

    def customer_money(self, customer_id: str) -> tuple[list[dict], list[dict]]:
        txns = self._run("select transaction_id, transaction_type as type, amount, currency, status, created_at, "
                         "estimated_arrival from transactions where customer_id = %s order by created_at desc",
                         (customer_id,), "all")
        payouts = self._run("select payout_id, transaction_id, amount, currency, status, scheduled_for from payouts "
                            "where customer_id = %s order by scheduled_for desc", (customer_id,), "all")
        return txns, payouts

    def reference_record(self, reference: str) -> tuple[str, dict] | None:
        """('transaction'|'payout', record) for a TXN- or PAY- reference."""
        if reference.startswith("TXN-"):
            row = self._run("select * from transactions where transaction_id = %s", (reference,), "one")
            return ("transaction", row) if row else None
        if reference.startswith("PAY-"):
            row = self._run("select * from payouts where payout_id = %s", (reference,), "one")
            return ("payout", row) if row else None
        return None
