"""[개선1] runbook RAG — 분할, 인덱스 재사용, 검색 질의 형식."""
from agent.config import DATA_DIR
from agent.nodes.runbook_agent import build_queries
from agent.rag.chunker import load_chunks, parse_runbook
from agent.rag.embeddings import FakeEmbedder
from agent.rag.index import ensure_index


def test_parse_runbook():
    chunks = parse_runbook("# Runbook: 테스트\n\n1. 첫 단계\n2. 둘째 단계", "test")
    assert [c["chunk_id"] for c in chunks] == ["test#0", "test#1", "test#2"]
    assert all(c["incident_type"] == "test" for c in chunks)


def test_all_runbooks_indexed():
    chunks, titles = load_chunks(DATA_DIR / "runbooks")
    assert len(titles) == 8 and {"queue-backlog", "cert-expiry"} <= set(titles)


async def test_index_rebuilt_only_when_changed(tmp_path):
    _, _, _, rebuilt1 = await ensure_index(FakeEmbedder(), index_root=tmp_path)
    _, _, _, rebuilt2 = await ensure_index(FakeEmbedder(), index_root=tmp_path)
    assert rebuilt1 and not rebuilt2


def test_query_uses_status_alerts_logs():
    state = {"query": "q", "targets": ["order-db"], "anomalies": ["order-db"], "evidence": [
        {"source": "monitoring", "data": {"system_name": "order-db", "status": "down", "alerts": ["a1"]}},
        {"source": "logs", "system": "order-db", "data": ["FATAL x"]}]}
    assert build_queries(state) == [("order-db", "상태=down. 알림: a1. 로그: FATAL x")]
    assert build_queries({"query": "q", "targets": ["web-01"], "anomalies": [], "evidence": []}) == [(None, "q")]
