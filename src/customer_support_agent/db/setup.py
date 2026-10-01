"""Create the tables and load the seed data: `poetry run relaypay-db`.

DATABASE_SCHEMA picks the set of tables: "public" (default, the real records) or e.g. "test", a separate
copy with its own ticket numbers for throwaway test runs: `DATABASE_SCHEMA=test poetry run relaypay-db`.

Safe to run more than once: the schema uses "create if not exists", and seed rows are upserted
(insert, or update if the ID already exists), so a re-run changes nothing and never duplicates.
"""

import logging
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from customer_support_agent.config import ConfigError, load_database_schema, load_database_url
from customer_support_agent.db.seed_data import SeedData, SeedError, load_seed
from customer_support_agent.logging_setup import configure_logging

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path("migrations")
EXIT_CONFIG_ERROR = 2
EXIT_FAILED = 1


def _upsert(cur: psycopg.Cursor, table: str, key: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != key)
    sql = (f"insert into {table} ({', '.join(columns)}) values ({', '.join('%s' for _ in columns)}) "
           f"on conflict ({key}) do update set {updates}")
    cur.executemany(sql, [tuple(row[c] for c in columns) for row in rows])


def apply_migrations(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    applied = []
    for path in sorted(migrations_dir.glob("*.sql")):
        conn.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


def load(conn: psycopg.Connection, seed: SeedData) -> None:
    with conn.cursor() as cur:  # parents first, because of the foreign keys
        _upsert(cur, "customers", "customer_id", seed.customers)
        _upsert(cur, "transactions", "transaction_id", seed.transactions)
        _upsert(cur, "payouts", "payout_id", seed.payouts)


def counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in ("customers", "transactions", "payouts")}


def main() -> int:
    load_dotenv()
    configure_logging()
    try:
        url = load_database_url()
        schema = load_database_schema()
        seed = load_seed()  # checked before connecting, so a bad file never half-loads the database
    except (ConfigError, SeedError) as exc:
        logger.error("Database setup not started: %s", exc)
        return EXIT_CONFIG_ERROR

    try:
        with psycopg.connect(url, connect_timeout=10) as conn:  # one transaction: all or nothing
            conn.execute(f"create schema if not exists {schema}")  # validated name, safe to inline
            conn.execute(f"set search_path to {schema}")
            applied = apply_migrations(conn)
            load(conn, seed)
            loaded = counts(conn)
    except psycopg.Error as exc:
        # psycopg messages don't include the password; the URL itself is never logged
        logger.error("Database setup failed and was rolled back: %s", exc)
        return EXIT_FAILED

    logger.info("Applied migrations to schema '%s': %s", schema, ", ".join(applied))
    logger.info("Rows now in the database: %s", loaded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
