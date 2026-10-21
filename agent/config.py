"""[개선5] 하드코딩 제거 — 흩어져 있던 상수·폴백 값을 data/ 설정 파일 한곳에서 읽는다.

Base에서는 같은 KNOWN_SYSTEMS 로딩 코드가 graph.py / ollama_llm.py / openai_llm.py 세 곳에
복사돼 있었고, 시스템을 못 찾으면 "auth-service", 장애 유형을 못 찾으면 "db-down"으로
조용히 폴백했다. 여기서는 시스템 목록·설명·별칭(data/monitoring.json), 동작 파라미터
(data/agent_config.json), 위험 조치 패턴(data/risk_policy.json)을 한 모듈에서 제공하고,
폴백 대신 "모르면 되묻는다"(clarify)로 바꿨다.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=None)
def systems() -> dict:
    """시스템 카탈로그: {이름: {status, cpu_base, memory_base, alerts, description, aliases}}."""
    return json.loads((DATA_DIR / "monitoring.json").read_text())


def known_systems() -> list[str]:
    return list(systems().keys())


@lru_cache(maxsize=None)
def agent_config() -> dict:
    return json.loads((DATA_DIR / "agent_config.json").read_text())


@lru_cache(maxsize=None)
def risk_policy() -> dict:
    return json.loads((DATA_DIR / "risk_policy.json").read_text())


def find_system_names(text: str) -> list[str]:
    """텍스트에 '이름 그대로' 등장한 시스템을 등장 순서대로 (Base의 멤버십 매칭과 같음)."""
    hits = [(text.index(s), s) for s in known_systems() if s in text]
    return [s for _, s in sorted(hits)]


def find_systems_by_alias(text: str) -> list[str]:
    """[개선5] 이름 대신 기능으로 말한 경우("로그인이 느려요")를 별칭으로 찾는다.
    Base는 이 경우 무조건 auth-service로 폴백했다."""
    lowered = text.lower()
    hits = []
    for name, info in systems().items():
        positions = [lowered.find(a.lower()) for a in info.get("aliases", []) if a.lower() in lowered]
        if positions:
            hits.append((min(positions), name))
    return [s for _, s in sorted(hits)]


def catalog_text() -> str:
    return "\n".join(f"- {name}: {info.get('description', '')}" for name, info in systems().items())


def runbook_types() -> list[str]:
    return sorted(p.stem for p in (DATA_DIR / "runbooks").glob("*.md"))


NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
