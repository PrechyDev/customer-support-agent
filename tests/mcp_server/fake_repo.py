"""An in-memory stand-in for the Supabase repository, with the seed data. Same method names."""

from datetime import date
from itertools import count

from customer_support_agent.db.repository import RepositoryUnavailable

CUSTOMERS = {
    "CUS-1001": {"customer_id": "CUS-1001", "company_name": "LagosLedger", "contact_name": "Amara Okafor",
                 "contact_email": "amara@lagosledger.example", "plan": "Growth", "account_status": "active",
                 "kyc_status": "approved", "support_notes": "Normal support access."},
    "CUS-1003": {"customer_id": "CUS-1003", "company_name": "AccraStack", "contact_name": "Efua Mensah",
                 "contact_email": "efua@accrastack.example", "plan": "Scale", "account_status": "restricted",
                 "kyc_status": "review required", "support_notes": "Account is under compliance review."},
}
TRANSACTIONS = {
    "TXN-9001": {"transaction_id": "TXN-9001", "customer_id": "CUS-1001", "status": "processing",
                 "estimated_arrival": date(2026, 8, 19)},
    "TXN-9004": {"transaction_id": "TXN-9004", "customer_id": "CUS-1003", "status": "failed", "estimated_arrival": None},
}
PAYOUTS = {
    "PAY-7002": {"payout_id": "PAY-7002", "transaction_id": "TXN-9003", "customer_id": "CUS-1003",
                 "status": "review required", "scheduled_for": date(2026, 8, 16), "failure_reason": "compliance review"},
}


class FakeRepository:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.conversations: dict[str, dict] = {}
        self.ticket_rows: list[dict] = []
        self.escalation_rows: list[dict] = []
        self.events: list[tuple] = []
        self.tool_calls: list[tuple] = []
        self.turns: list[tuple] = []
        self.closed: list[tuple] = []
        self._ids = count(1001)

    def _check(self):
        if self.down:
            raise RepositoryUnavailable("database down")

    def ensure_conversation(self, cid, model=None, caller=None):
        self._check()
        conv = self.conversations.setdefault(cid, {"conversation_id": cid, "verification_attempts": 0,
                                                    "verified_customer_id": None, "caller_name": None,
                                                    "caller_email": None, "caller_company": None, "model": None,
                                                    "last_verification_try": None})
        conv["model"] = model or conv["model"]
        for key in ("name", "email", "company"):
            if caller and caller.get(key):
                conv[f"caller_{key}"] = caller[key]
        return dict(conv)

    def record_verification_attempt(self, cid, fingerprint):
        self.conversations[cid]["last_verification_try"] = fingerprint
        self.conversations[cid]["verification_attempts"] += 1
        return self.conversations[cid]["verification_attempts"]

    def mark_verified(self, cid, customer_id):
        self.conversations[cid]["verified_customer_id"] = customer_id

    def close_conversation(self, cid, summary):
        self.closed.append((cid, summary))

    def mark_abandoned(self, cid):
        self.closed.append((cid, "abandoned"))

    def customer_by_email(self, email):
        return next((c for c in CUSTOMERS.values() if c["contact_email"] == email), None)

    def customer(self, customer_id):
        return CUSTOMERS.get(customer_id)

    def transaction(self, ref):
        self._check()
        return TRANSACTIONS.get(ref)

    def payout(self, ref):
        return PAYOUTS.get(ref)

    def payout_for_transaction(self, ref):
        return next((p for p in PAYOUTS.values() if p["transaction_id"] == ref), None)

    def ticket(self, cid, category, reference):
        return next((t for t in self.ticket_rows
                     if (t["conversation_id"], t["category"], t["reference"]) == (cid, category, reference)), None)

    def tickets(self, cid):
        return [t for t in self.ticket_rows if t["conversation_id"] == cid]

    def create_ticket(self, cid, customer_id, category, priority, summary, reference):
        existing = self.ticket(cid, category, reference)
        if existing:
            return existing["ticket_id"], False
        ticket = {"ticket_id": f"T-{next(self._ids)}", "conversation_id": cid, "customer_id": customer_id,
                  "category": category, "priority": priority, "summary": summary, "reference": reference,
                  "status": "open"}
        self.ticket_rows.append(ticket)
        return ticket["ticket_id"], True

    def escalation(self, cid, category):
        return next((e for e in self.escalation_rows if (e["conversation_id"], e["category"]) == (cid, category)), None)

    def escalations(self, cid):
        return [e for e in self.escalation_rows if e["conversation_id"] == cid]

    def create_escalation(self, values, event_summary, event_metadata):
        existing = self.escalation(values["conversation_id"], values["category"])
        if existing:
            return existing["escalation_id"], False
        self.escalation_rows.append({"escalation_id": f"E-{next(self._ids)}", "status": "open", **values})
        self.log_event(values["conversation_id"], "escalation_created", event_summary, event_metadata)
        return self.escalation_rows[-1]["escalation_id"], True

    def set_callback(self, escalation_id, values):
        next(e for e in self.escalation_rows if e["escalation_id"] == escalation_id).update(values)

    def log_event(self, cid, event_type, summary, metadata=None):
        self.events.append((cid, event_type, summary))

    def log_tool_call(self, *args):
        self.tool_calls.append(args)

    def log_turn(self, *args):
        self.turns.append(args)
