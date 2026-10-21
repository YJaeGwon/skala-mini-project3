"""Base의 키워드 기반 장애 유형 분류(graph.py _INCIDENT_TYPE_RULES)를 그대로 옮겨, 한계를 테스트로 기록한다.
이 테스트들은 '버그가 있음'을 확인한다 — [개선1] RAG로 바꾼 이유."""
from agent.config import systems

RULES = [("latency", "high-latency"), ("pool", "high-latency"), ("cpu", "cpu-spike"),
         ("memory", "memory-leak"), ("heap", "memory-leak"), ("timeout", "network-timeout"),
         ("network", "network-timeout"), ("disk", "disk-full"), ("down", "db-down")]


def base_classify(system_names):
    text = " ".join(f"{systems()[s]['status']} " + " ".join(systems()[s]["alerts"]) for s in system_names).lower()
    return next((t for k, t in RULES if k in text), "db-down")


def test_base_picks_only_one_type_for_mixed_incident():
    assert base_classify(["gateway-service", "payments-service"]) == "cpu-spike"   # timeout을 놓침


def test_base_cannot_use_new_runbooks():
    assert base_classify(["notification-service"]) == "db-down"   # 정답 queue-backlog
    assert base_classify(["edge-proxy"]) == "db-down"             # 정답 cert-expiry
