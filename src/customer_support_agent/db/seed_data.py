"""Read and check the seed CSVs (data/seed/) before anything touches the database.

Every row is validated here (required fields, allowed statuses, dates, amounts), so a bad file
fails with the file name and row number instead of a half-loaded database.
"""

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SEED_DIR = Path("data/seed")

ACCOUNT_STATUSES = {"active", "restricted", "pending verification"}
KYC_STATUSES = {"pending", "approved", "review required"}
PLANS = {"Starter", "Growth", "Scale"}
TRANSACTION_TYPES = {"incoming transfer", "outgoing payout", "invoice payment"}
TRANSACTION_STATUSES = {"processing", "completed", "delayed", "failed", "review required"}
PAYOUT_STATUSES = {"scheduled", "processing", "completed", "failed", "review required"}


class SeedError(ValueError):
    """A seed file is missing or has a bad row."""


@dataclass(frozen=True)
class SeedData:
    customers: list[dict[str, Any]]
    transactions: list[dict[str, Any]]
    payouts: list[dict[str, Any]]


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]
    except FileNotFoundError:
        raise SeedError(f"Seed file not found: {path}") from None


class _Row:
    """Typed access to one CSV row, with errors that name the file and row."""

    def __init__(self, path: Path, number: int, row: dict[str, str]) -> None:
        self._where = f"{path.name} row {number}"
        self._row = row

    def text(self, field: str, required: bool = True) -> str | None:
        value = self._row.get(field, "")
        if required and not value:
            raise SeedError(f"{self._where}: '{field}' is empty")
        return value or None

    def choice(self, field: str, allowed: set[str]) -> str:
        value = self.text(field)
        if value not in allowed:
            raise SeedError(f"{self._where}: '{field}' is '{value}', expected one of {sorted(allowed)}")
        return value

    def amount(self, field: str) -> Decimal:
        try:
            value = Decimal(self.text(field))
        except InvalidOperation:
            raise SeedError(f"{self._where}: '{field}' is not a number") from None
        if value < 0:
            raise SeedError(f"{self._where}: '{field}' is negative")
        return value

    def day(self, field: str, required: bool = True) -> date | None:
        value = self.text(field, required)
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise SeedError(f"{self._where}: '{field}' is not a YYYY-MM-DD date") from None


def _read(path: Path) -> list[_Row]:
    return [_Row(path, i, row) for i, row in enumerate(_rows(path), start=2)]  # row 1 is the header


def load_seed(seed_dir: Path = SEED_DIR) -> SeedData:
    customers = [
        {"customer_id": r.text("customer_id"), "company_name": r.text("company_name"),
         "contact_name": r.text("contact_name"), "contact_email": r.text("contact_email"),
         "plan": r.choice("plan", PLANS), "account_status": r.choice("account_status", ACCOUNT_STATUSES),
         "region": r.text("region"), "kyc_status": r.choice("kyc_status", KYC_STATUSES),
         "support_notes": r.text("support_notes", required=False) or ""}
        for r in _read(seed_dir / "customers.csv")
    ]
    transactions = [
        {"transaction_id": r.text("transaction_id"), "customer_id": r.text("customer_id"),
         "transaction_type": r.choice("transaction_type", TRANSACTION_TYPES), "amount": r.amount("amount"),
         "currency": r.text("currency"), "destination_country": r.text("destination_country", required=False),
         "status": r.choice("status", TRANSACTION_STATUSES), "created_at": r.day("created_at"),
         "estimated_arrival": r.day("estimated_arrival", required=False),
         "support_summary": r.text("support_summary", required=False) or ""}
        for r in _read(seed_dir / "transactions.csv")
    ]
    payouts = [
        {"payout_id": r.text("payout_id"), "transaction_id": r.text("transaction_id"),
         "customer_id": r.text("customer_id"), "recipient_name": r.text("recipient_name"),
         "amount": r.amount("amount"), "currency": r.text("currency"),
         "status": r.choice("status", PAYOUT_STATUSES), "scheduled_for": r.day("scheduled_for", required=False),
         "failure_reason": r.text("failure_reason", required=False)}
        for r in _read(seed_dir / "payouts.csv")
    ]
    return SeedData(customers=customers, transactions=transactions, payouts=payouts)
