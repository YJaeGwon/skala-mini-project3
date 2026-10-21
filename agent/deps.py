"""의존성 주입 (Base Wave 13 패턴 확장).

노드 함수는 전역 변수에 기대지 않고, 필요한 의존성을 SupervisorDeps 하나로 주입받는다.
과제1에서 추가된 의존성: judge_llm(평가), retriever(runbook RAG), config, backend.
테스트에서는 FakeMCP·fake LLM·임시 인덱스로 갈아 끼우기만 하면 된다.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SupervisorDeps:
    fast_llm: Any        # 라우팅·대상 해석·요약·잡담 — 저비용 모델
    quality_llm: Any     # 최종 답변 작성 — 고품질 모델
    mcp: Any             # MCP 클라이언트 (Tool/Resource/Prompt)
    session_store: Any   # SQLite 세션 저장소 (+ [추가3] 요약 메모리)
    version: str         # v1 | v2
    retriever: Any = None        # [개선1] runbook RAG 검색기
    judge_llm: Any = None        # [추가2] 평가 전용
    config: dict = field(default_factory=dict)
    backend: str = "fake"
