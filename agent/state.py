"""그래프 상태 정의.

events / collected / cost_usd / retry_count에는 operator.add reducer를 붙였다 — 메트릭
에이전트와 로그 에이전트가 병렬로 실행되며 같은 키에 동시에 쓰기 때문이다. 그래서 모든
노드는 이 키들에 대해 '전체 값'이 아니라 '이번에 늘어난 변경분'만 반환한다.
(Base는 노드마다 전체 리스트를 다시 만들어 반환하는 방식이라 병렬 쓰기를 할 수 없었다.)
"""
import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict, total=False):
    query: str
    thread_id: str
    run_id: str
    history: list[dict]          # [추가3] 최근 대화 (오래된 대화는 memory_summary로 압축)
    memory_summary: str
    route: str                   # chat | incident | clarify
    needs_analysis: bool
    targets: list[str]
    target_source: str           # explicit | alias | history | llm | none
    tasks: list[dict]
    gate_removed: int
    anomalies: list[str]         # 메트릭 에이전트가 이상으로 판단한 시스템
    runbooks: list[dict]         # [{system, incident_type, score}]
    draft: str
    validation_attempts: int
    validation_feedback: str | None
    validation_failures: list[str]
    used_fallback: bool
    risky_actions: list[str]
    approval: dict | None
    final: str
    last_prompt: str
    # reducer 키 — 노드는 변경분만 반환한다
    collected: Annotated[list[dict], operator.add]
    events: Annotated[list[dict], operator.add]
    cost_usd: Annotated[float, operator.add]
    retry_count: Annotated[int, operator.add]


class MetricAgentState(TypedDict, total=False):
    targets: list[str]
    collected: Annotated[list[dict], operator.add]
    anomalies: list[str]
    events: Annotated[list[dict], operator.add]
    retry_count: Annotated[int, operator.add]


class LogAgentState(TypedDict, total=False):
    targets: list[str]
    raw: list[dict]              # MCP 원본 응답 (filter 전)
    collected: Annotated[list[dict], operator.add]
    events: Annotated[list[dict], operator.add]


class RunbookAgentState(TypedDict, total=False):
    query: str
    targets: list[str]
    evidence: list[dict]         # 메트릭·로그 수집 결과 (검색 질의를 만드는 재료)
    anomalies: list[str]
    selections: list[dict]
    collected: Annotated[list[dict], operator.add]
    events: Annotated[list[dict], operator.add]
