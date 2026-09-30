from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from customer_support_agent.config import ConfigError, load_database_url
from customer_support_agent.db.seed_data import SeedError, load_seed

SEED_DIR = Path(__file__).parents[2] / "data" / "seed"


def test_real_seed_files_load_with_types():
    seed = load_seed(SEED_DIR)
    assert (len(seed.customers), len(seed.transactions), len(seed.payouts)) == (5, 5, 3)
    txn = {t["transaction_id"]: t for t in seed.transactions}
    assert txn["TXN-9001"]["amount"] == Decimal("2400") and txn["TXN-9001"]["estimated_arrival"] == date(2026, 8, 19)
    assert txn["TXN-9003"]["estimated_arrival"] is None  # review required: no ETA
    assert {p["payout_id"]: p for p in seed.payouts}["PAY-7001"]["failure_reason"] is None


def test_bad_seed_row_names_the_file_and_row(tmp_path):
    for name in ("customers.csv", "transactions.csv", "payouts.csv"):
        (tmp_path / name).write_text((SEED_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    bad = (tmp_path / "transactions.csv").read_text(encoding="utf-8").replace(",processing,", ",lost,", 1)
    (tmp_path / "transactions.csv").write_text(bad, encoding="utf-8")
    with pytest.raises(SeedError, match="transactions.csv row 2: 'status' is 'lost'"):
        load_seed(tmp_path)


def test_database_url_is_checked_without_leaking_it():
    assert load_database_url({"DATABASE_URL": "postgresql://u:p@h:5432/db"}).startswith("postgresql://")
    for bad in ({}, {"DATABASE_URL": "mysql://x"}, {"DATABASE_URL": "postgresql://u:[YOUR-PASSWORD]@h/db"}):
        with pytest.raises(ConfigError) as exc:
            load_database_url(bad)
        assert "u:" not in str(exc.value)
