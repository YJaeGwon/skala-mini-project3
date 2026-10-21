"""[개선5] 설정·시스템 해석 — 하드코딩 폴백 대신 이름·별칭으로 찾는다."""
from agent.config import agent_config, find_system_names, find_systems_by_alias, known_systems, runbook_types


def test_catalog_has_new_systems_and_runbooks():
    assert {"order-db", "notification-service", "edge-proxy"} <= set(known_systems())
    assert {"queue-backlog", "cert-expiry"} <= set(runbook_types())


def test_names_in_order():
    assert find_system_names("gateway-service에서 payments-service로 가는 요청") == \
        ["gateway-service", "payments-service"]


def test_alias_lookup():
    assert find_systems_by_alias("로그인 응답이 느려요") == ["auth-service"]
    assert find_systems_by_alias("고객들이 알림을 늦게 받는대요") == ["notification-service"]
    assert find_systems_by_alias("접속할 때 인증서 경고가 떠요") == ["edge-proxy"]
    assert find_systems_by_alias("서비스가 좀 이상해요") == []


def test_config_values():
    c = agent_config()
    assert c["validate_max_attempts"] == 3 and c["memory_keep_recent"] < c["memory_max_messages"]
