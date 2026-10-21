"""[개선2] 사실 검증 + [추가1] 위험 조치 탐지."""
from agent.config import risk_policy
from agent.validators import (check_format, check_numbers, check_systems, extract_metrics,
                              find_risky, strip_risky)

COLLECTED = [
    {"source": "monitoring", "data": {"system_name": "payments-service", "status": "degraded",
                                      "cpu_percent": 93.4, "memory_percent": 55.2,
                                      "alerts": ["CPU 91% (threshold 80%)", "payments-service-3 instance responding slow"]}},
    {"source": "logs", "system": "gateway-service",
     "data": ["ERROR upstream timed out (110) while reading response header from payments-service"]},
    {"source": "runbook", "system": "payments-service", "incident_type": "cpu-spike",
     "data": "# Runbook: CPU 급증\n3. CPU가 90%를 넘고 지속되면 오토스케일링"},
]


def test_extract_metrics():
    assert extract_metrics("CPU 93.4%, p95 2.4s, 3000ms, 5초") == \
        [(93.4, "%"), (2.4, "s"), (3000.0, "ms"), (5.0, "s")]


def test_format_like_base():
    assert check_format("재시작하면 됩니다.")                       # Base Wave 8 반려 사례 그대로
    assert check_format("1) payments-service CPU 93.4% 확인 2) runbook 절차 수행") == []


def test_numbers_must_come_from_evidence():
    assert check_numbers("CPU 93.4%, 임계치 80%, runbook 기준 90%", COLLECTED) == []
    assert check_numbers("CPU 93%로 측정", COLLECTED) == []           # 반올림 인용은 허용
    assert check_numbers("cache-service CPU 53.5%", COLLECTED)        # Base 주석의 실측 환각 사례


def test_systems_must_be_investigated():
    assert check_systems("payments-service와 gateway-service 확인", ["payments-service"], COLLECTED) == []
    assert check_systems("cache-service도 원인일 수 있음", ["payments-service"], COLLECTED)


def test_risky_detection_excludes_checks():
    draft = "1) 프로세스를 즉시 재시작해 중단을 막는다.\n2) 워커가 재시작 반복 상태인지 확인한다.\n3) 직전 배포를 롤백한다."
    risky = find_risky(draft, risk_policy())
    assert len(risky) == 2 and all("반복" not in r for r in risky)


def test_strip_risky_renumbers():
    draft = "1) 지표 확인\n2) 즉시 재시작한다.\n3) 원인 분석"
    out = strip_risky(draft, risk_policy())
    assert out.splitlines()[:2] == ["1) 지표 확인", "2) 원인 분석"] and "재시작한다" not in out
