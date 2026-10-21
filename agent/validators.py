"""[개선2] 답변 검증 — 형식 검사 + 사실 검증.

Base의 validate는 "30자 이상 + '1)' 포함"만 봤다. 그래서 수집하지 않은 CPU 수치를 지어내도
통과했다(Base openai_llm.py 주석의 실측 사례: 조사하지 않은 cache-service의 'CPU 53.5%').
여기서는 형식 검사를 유지하면서 아래를 추가로 검사한다.
- 수치: 답변의 %, 초(s), ms 값이 수집된 모니터링 값이나 알림·로그·runbook 본문에 실제로 있는가
- 시스템: 답변이 언급한 시스템이 실제로 조사했거나 수집된 근거에 등장한 시스템인가
각 check_* 함수는 실패 사유 리스트를 돌려준다(빈 리스트면 통과). 평가 지표도 같은 함수를 쓴다.

[추가1] 위험 조치 탐지(find_risky)와 제거(strip_risky)도 여기 둔다.
"""
import re

from .config import find_system_names

METRIC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|ms|초|s)(?![a-zA-Z])")


def extract_metrics(text: str) -> list[tuple[float, str]]:
    return [(float(v), "s" if u == "초" else u) for v, u in METRIC_RE.findall(text)]


def _evidence_texts(collected: list[dict]) -> list[str]:
    texts = []
    for c in collected:
        if c["source"] == "monitoring":
            texts.extend(c["data"].get("alerts", []))
        elif c["source"] == "logs":
            texts.extend(c["data"])
        elif c["source"] in ("runbook", "analysis"):
            texts.append(c["data"])
    return texts


def allowed_metrics(collected: list[dict]) -> set[tuple[float, str]]:
    allowed: set[tuple[float, str]] = set()
    for c in collected:
        if c["source"] == "monitoring":
            allowed.add((float(c["data"]["cpu_percent"]), "%"))
            allowed.add((float(c["data"]["memory_percent"]), "%"))
    for text in _evidence_texts(collected):
        allowed.update(extract_metrics(text))
    return allowed


def _matches(value: float, unit: str, allowed: set[tuple[float, str]]) -> bool:
    for av, au in allowed:
        if au != unit:
            continue
        # 91.3% → "91%"처럼 정수로 반올림해 인용한 것은 허용한다
        if abs(value - av) <= 0.05 or (value.is_integer() and round(av) == value):
            return True
    return False


def check_format(draft: str, min_length: int = 30) -> list[str]:
    failures = []
    if len(draft) < min_length:
        failures.append(f"응답이 너무 짧습니다({len(draft)}자, 최소 {min_length}자).")
    if "1)" not in draft:
        failures.append("절차를 1) 2) 3) 번호로 구체적으로 설명하세요.")
    return failures


def check_numbers(draft: str, collected: list[dict]) -> list[str]:
    allowed = allowed_metrics(collected)
    bad = [f"{v:g}{u}" for v, u in extract_metrics(draft) if not _matches(v, u, allowed)]
    if not bad:
        return []
    return [f"수집되지 않은 수치를 썼습니다: {', '.join(dict.fromkeys(bad))}. "
            "모니터링·로그·runbook에 있는 값만 그대로 인용하세요."]


def check_systems(draft: str, targets: list[str], collected: list[dict]) -> list[str]:
    allowed = set(targets)
    for c in collected:   # 실제로 지표·로그를 수집한 시스템
        if c["source"] == "monitoring":
            allowed.add(c["data"]["system_name"])
        elif c["source"] == "logs":
            allowed.add(c["system"])
    for text in _evidence_texts(collected):   # 알림·로그에 등장한 시스템 (예: "upstream timeout to payments-service")
        allowed.update(find_system_names(text))
    unknown = [s for s in find_system_names(draft) if s not in allowed]
    if not unknown:
        return []
    return [f"조사하지 않은 시스템({', '.join(unknown)})에 대해 언급했습니다. "
            f"조사한 시스템({', '.join(targets)})만 진단하세요."]


def run_all(draft: str, *, targets: list[str], collected: list[dict], min_length: int) -> list[str]:
    return (check_format(draft, min_length) + check_numbers(draft, collected)
            + check_systems(draft, targets, collected))


# ── [추가1] 위험 조치 ──────────────────────────────────────────────────
STEP_RE = re.compile(r"^\s*\d+\)\s*")


def _is_risky(segment: str, policy: dict) -> bool:
    low = segment.lower()
    return (any(p.lower() in low for p in policy["high_risk_patterns"])
            and not any(x in segment for x in policy.get("exclude_contexts", [])))


def _sentences(line: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]


def find_risky(draft: str, policy: dict) -> list[str]:
    """위험 조치를 '실행하라'는 문장을 찾는다 (점검·확인 문맥은 제외)."""
    return [s.strip() for line in draft.splitlines() for s in _sentences(line) if _is_risky(s, policy)]


def strip_risky(draft: str, policy: dict) -> str:
    """승인 거절 후에도 남은 위험 조치를 지운다. 번호 단계(1) 2) …)는 줄째로 지우고 번호를 다시 매긴다."""
    kept = []
    for line in draft.splitlines():
        if STEP_RE.match(line):
            if not any(_is_risky(s, policy) for s in _sentences(line)):
                kept.append(STEP_RE.sub("", line))
        else:
            rest = [s for s in _sentences(line) if not _is_risky(s, policy)]
            if rest:
                kept.append(" ".join(rest))
    numbered, n = [], 1
    for line in kept:
        numbered.append(f"{n}) {line}")
        n += 1
    numbered.append("※ 서비스 중단 위험이 있는 조치(재시작·롤백·failover 등)는 운영 승인이 거절되어 제외했습니다.")
    return "\n".join(numbered)
