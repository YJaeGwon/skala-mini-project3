"""[개선3] 조사 Supervisor — Base의 단일 research 노드를 전문 서브에이전트 3개로 나눴다.

  metric_agent(모니터링 지표)  ─┐  병렬
  log_agent   (최근 에러 로그) ─┘
          ↓ 둘 다 끝나면
  runbook_agent(RAG로 대응 절차 선택) — 지표·로그에서 찾은 증상으로 runbook을 검색

runbook 선택은 지표·로그 결과가 있어야 정확해서 이 순서로 연결했다(graph.py).
"""
from langsmith import traceable


@traceable(name="research_supervisor_node")
async def research_supervisor_node(state: dict, deps) -> dict:
    return {"events": [{"type": "ResearchPlanned", "targets": state["targets"],
                        "agents": ["metric_agent", "log_agent", "runbook_agent"]}]}
