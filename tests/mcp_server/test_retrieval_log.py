import json

from customer_support_agent.mcp_server.retrieval_log import JsonlRetrievalLogStore, RetrievalRecord


def test_appends_one_json_line_per_record_with_utc_time(tmp_path):
    path = tmp_path / "logs" / "retrieval.jsonl"  # folder doesn't exist yet
    store = JsonlRetrievalLogStore(path)
    store.record(RetrievalRecord("call-1", "fees", ("how-does-relaypay-charge-fees",), ("FAQ > Fees",), (6.11,), 0.4))
    store.record(RetrievalRecord("call-1", "pizza", (), (), (), 0.1))

    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first["chunk_ids"] == ["how-does-relaypay-charge-fees"] and first["scores"] == [6.11]
    assert first["timestamp"].endswith("+00:00")
    assert second["chunk_ids"] == []
