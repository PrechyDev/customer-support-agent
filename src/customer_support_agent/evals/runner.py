"""Run the evaluation scenarios through the running backend and score them from the database.

    poetry run relaypay-eval                          all scenarios (text, no Vapi, no phone costs)
    poetry run relaypay-eval --only s1_fees,e1_injection
    poetry run relaypay-eval --call <vapi-call-id> --scenario s4_transaction    score a real voice call

Scripted runs send Vapi-shaped requests (call ID, form metadata, the shared secret) to `/chat/completions`,
exactly as Vapi does, then the end-of-call event. So they exercise the real agent, MCP tools and database
writes; each costs a Claude call per line (about $0.02 per scenario). The backend and the MCP server must be
running with DATABASE_SCHEMA=test, so evaluation calls never mix with real records. Each result is stored in
`evaluations` (one run ID per run) and printed as a table.
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from dotenv import find_dotenv, load_dotenv

from customer_support_agent.config import ConfigError, load_database_schema, load_database_url
from customer_support_agent.db.repository import Repository, RepositoryUnavailable
from customer_support_agent.evals.record import Score, load_record, score
from customer_support_agent.evals.scenarios import BY_KEY, SCENARIOS, Scenario
from customer_support_agent.logging_setup import configure_logging

logger = logging.getLogger(__name__)

Post = Callable[[str, dict], dict]
TURN_TIMEOUT_SECONDS = 60
RECORDS_WAIT_SECONDS = 15  # background writes land within a second or two


class EvalError(Exception):
    """The run can't go ahead (backend down, wrong secret, wrong schema). The message says what to fix."""


def http_post(base_url: str, secret: str) -> Post:
    def post(path: str, body: dict) -> dict:
        request = urllib.request.Request(f"{base_url}{path}", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-RelayPay-Secret": secret})
        try:
            with urllib.request.urlopen(request, timeout=TURN_TIMEOUT_SECONDS) as response:  # noqa: S310 (our URL)
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise EvalError("The backend refused the secret: VAPI_LLM_SECRET must match the backend's.") from None
            raise EvalError(f"The backend answered {exc.code} on {path}.") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise EvalError(f"Can't reach the backend at {base_url} ({exc}). Start it (and the MCP server) "
                            "with DATABASE_SCHEMA=test.") from None
    return post


def play(scenario: Scenario, cid: str, post: Post) -> list[str]:
    """Says the scenario's lines as one call and returns the agent's replies."""
    call = {"id": cid, "assistantOverrides": {"metadata": scenario.form}}
    post("/vapi/events", {"message": {"type": "status-update", "status": "in-progress", "call": call}})
    messages: list[dict] = []
    replies: list[str] = []
    for line in scenario.lines:
        if not line.applies(replies[-1] if replies else ""):
            continue
        messages = [*messages, {"role": "user", "content": line.text}]
        answer = post("/chat/completions", {"stream": False, "call": call, "messages": messages})
        reply = answer["choices"][0]["message"]["content"] or ""
        messages = [*messages, {"role": "assistant", "content": reply}]
        replies.append(reply)
    post("/vapi/events", {"message": {"type": "end-of-call-report", "call": call, "endedReason": "eval-finished"}})
    return replies


def wait_for_record(repo: Any, cid: str, sleep: Callable[[float], None] = time.sleep):
    """The call's records once the end of the call is written (writes run in the background)."""
    deadline = time.monotonic() + RECORDS_WAIT_SECONDS
    while True:
        record = load_record(repo, cid)
        if record.ended or time.monotonic() > deadline:
            return record
        sleep(0.5)


def save(repo: Any, run_id: str, scenario: Scenario, result: Score, cid: str) -> None:
    notes = f"call {cid}" + (f"; failed: {'; '.join(result.failed)}" if result.failed else "")
    repo._run("insert into evaluations (run_id, scenario, expected_behavior, actual_behavior, passed, notes) "
              "values (%s, %s, %s, %s, %s, %s)",
              (run_id, f"{scenario.key}: {scenario.title}", scenario.expected, result.actual, result.passed, notes))


def run(scenarios: list[Scenario], repo: Any, post: Post, run_id: str) -> list[tuple[Scenario, Score]]:
    results = []
    for scenario in scenarios:
        cid = f"eval-{run_id}-{scenario.key}"
        play(scenario, cid, post)
        record = wait_for_record(repo, cid)
        if not record.exists:
            raise EvalError(f"No records for {cid} in schema '{repo.schema}': is the backend running with "
                            f"DATABASE_SCHEMA={repo.schema}?")
        result = score(scenario.checks, record)
        save(repo, run_id, scenario, result, cid)
        logger.info("Eval %s: %s", scenario.key, "pass" if result.passed else "FAIL")
        results.append((scenario, result))
    return results


def report(results: list[tuple[Scenario, Score]], run_id: str) -> str:
    lines = [f"Run {run_id}", f"{'scenario':<26} {'result':<6} notes"]
    for scenario, result in results:
        lines.append(f"{scenario.key:<26} {'PASS' if result.passed else 'FAIL':<6} {'; '.join(result.failed)}")
    passed = sum(r.passed for _, r in results)
    lines.append(f"{passed}/{len(results)} passed")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or score the RelayPay evaluation scenarios.")
    parser.add_argument("--only", help="comma-separated scenario keys (default: all)")
    parser.add_argument("--call", help="score this existing call instead of running a script")
    parser.add_argument("--scenario", help="with --call: the scenario to score it against")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--schema", help="with --call: public or test (default: DATABASE_SCHEMA)")
    args = parser.parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))
    configure_logging("WARNING")

    keys = [k.strip() for k in (args.scenario or args.only or "").split(",") if k.strip()]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown or (args.call and len(keys) != 1):
        print(f"Pick {'one scenario' if args.call else 'scenarios'} from: {', '.join(BY_KEY)}")
        return 2
    chosen = [BY_KEY[k] for k in keys] or list(SCENARIOS)
    try:
        schema = args.schema or load_database_schema()
        if not args.call and schema == "public":
            raise ConfigError("scripted evaluations write calls, so run them on the test schema: "
                              "DATABASE_SCHEMA=test for this command and the backend")
        repo = Repository(load_database_url(), schema)
    except ConfigError as exc:
        print(f"Not run: {exc}")
        return 2

    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M") + "-" + uuid.uuid4().hex[:4]
    repo.open()
    try:
        if args.call:
            record = load_record(repo, args.call)
            result = score(chosen[0].checks, record)
            if record.exists:
                save(repo, run_id, chosen[0], result, args.call)
            results = [(chosen[0], result)]
        else:
            results = run(chosen, repo, http_post(args.base_url.rstrip("/"), os.environ.get("VAPI_LLM_SECRET", "")),
                          run_id)
    except (EvalError, RepositoryUnavailable) as exc:
        print(f"Stopped: {exc}")
        return 1
    finally:
        repo.close()
    print(report(results, run_id))
    for scenario, result in results:
        print(f"\n{scenario.key}: {result.actual}")
    return 0 if all(r.passed for _, r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
