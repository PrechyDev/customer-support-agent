import json

from customer_support_agent.mcp_server.retrieval_log import JsonlRetrievalLogStore, RetrievalRecord


def make_record(**overrides):
    fields = dict(
        conversation_id="call-123",
        query="fees international payments",
        chunk_ids=("how-does-relaypay-charge-fees",),
        titles=("Frequently Asked Questions > How Does RelayPay Charge Fees?",),
        scores=(6.11,),
        duration_ms=0.4,
    )
    fields.update(overrides)
    return RetrievalRecord(**fields)


def test_writes_one_json_line_per_record(tmp_path):
    path = tmp_path / "logs" / "retrieval.jsonl"  # parent folder doesn't exist yet
    store = JsonlRetrievalLogStore(path)

    store.record(make_record())
    store.record(make_record(query="payment delayed"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["conversation_id"] == "call-123"
    assert first["chunk_ids"] == ["how-does-relaypay-charge-fees"]
    assert first["scores"] == [6.11]
    assert first["timestamp"].endswith("+00:00")  # real UTC time
    assert json.loads(lines[1])["query"] == "payment delayed"


def test_record_with_no_results_is_still_logged(tmp_path):
    path = tmp_path / "retrieval.jsonl"
    JsonlRetrievalLogStore(path).record(make_record(chunk_ids=(), titles=(), scores=()))
    assert json.loads(path.read_text(encoding="utf-8"))["chunk_ids"] == []
