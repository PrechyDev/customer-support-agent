"""Create the superadmin (the owner) for the support console: `poetry run relaypay-admin --email you@example.com`.

Prints a one-time setup link (72 h) where the owner sets their name and password. No password is ever put in
.env or typed into a terminal. Only one superadmin can exist; `--reset` issues a new link for them (forgotten
password, or the first link expired). Uses DATABASE_SCHEMA like the backend (test or public).
"""

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

from dotenv import find_dotenv, load_dotenv

from customer_support_agent.config import ConfigError, load_console_settings, load_database_schema, load_database_url
from customer_support_agent.console import security
from customer_support_agent.db.console_store import ConsoleStore
from customer_support_agent.db.repository import Repository, RepositoryUnavailable
from customer_support_agent.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or reset the console superadmin.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--reset", action="store_true", help="new setup link for the existing superadmin")
    args = parser.parse_args()
    load_dotenv(find_dotenv(usecwd=True))
    configure_logging("WARNING")

    email = security.normalise_email(args.email)
    if not email:
        print("That isn't a valid email.")
        return 2
    try:
        settings, schema = load_console_settings(), load_database_schema()
        repo = Repository(load_database_url(), schema)
    except ConfigError as exc:
        print(f"Not done: {exc}")
        return 2
    repo.open()
    try:
        store = ConsoleStore(repo)
        existing = next((m for m in store.members() if m["role"] == "superadmin"), None)
        token, digest = security.new_link_token()
        expires = datetime.now(UTC) + timedelta(seconds=security.INVITE_SECONDS)
        if existing:
            if not args.reset or existing["email"] != email:
                print(f"A superadmin already exists ({existing['email']}). Use --reset with that email for a new link.")
                return 1
            store.set_link(existing["member_id"], digest, "reset" if existing["status"] == "active" else "invite",
                           expires)
        elif store.create_member(email, "superadmin", None, digest, "invite", expires) is None:
            print("That email is already a team member with another role.")
            return 1
    except RepositoryUnavailable as exc:
        print(f"Database unavailable: {exc}")
        return 1
    finally:
        repo.close()

    base = settings.public_base_url or "http://127.0.0.1:8000"
    print(f"Schema: {schema}\nSetup link for {email} (valid 72 hours, single use):\n{base}/console/invite/{token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
