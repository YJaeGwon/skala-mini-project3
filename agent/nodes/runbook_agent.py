"""[개선1] runbook 서브에이전트 (compiled subgraph, RAG): select → fetch

Base: 모니터링 알림 문구에서 키워드('latency', 'cpu', 'memory'…)를 위에서부터 찾아 첫 번째로
걸린 장애 유형 '하나'만 골랐다. 그래서
  - 'gateway→payments 타임아웃'처럼 여러 증상이 섞이면 순서상 먼저 걸린 cpu-spike만 가져오고
  - 키워드 목록에 없는 새 장애(인증서 만료, 큐 적체)는 무조건 db-down으로 폴백했다.
개선:
  - select: 이상 시스템마다 '알림 + 에러 로그'를 검색 질의로 만들어 runbook을 의미 검색(RAG)
            → 시스템별로 장애 유형을 고르고 중복 제거 (최대 max_runbooks개)
            이상 시스템이 없으면 사용자 질문으로 검색, 점수가 임계값 미만이면 고르지 않는다
  - fetch : 고른 runbook 원문을 MCP Resource(runbook://incident-response/{type})로 가져온다
"""
from functools import partial

from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from ..state import RunbookAgentState


def _min_score(deps) -> float:
    return deps.config["runbook_min_score"].get(deps.backend, 0.25)


def build_queries(state: RunbookAgentState) -> list[tuple[str | None, str]]:
    """반환: [(시스템 또는 None, 검색 질의)].

    질의 형식 "상태=down. 알림: ... 로그: ..." — 실측으로 정했다(OpenAI 임베딩, 이상 시스템 8개):
      알림+로그만 7/8 (order-db를 network-timeout으로 오분류), 시스템 설명까지 넣으면 7/8
      ('인증' 단어 때문에 auth-service가 cert-expiry로), 상태값을 넣으면 8/8."""
    evidence = state.get("evidence", [])
    queries = []
    for system in state.get("anomalies", []):
        status, alerts, logs = "", [], []
        for c in evidence:
            if c["source"] == "monitoring" and c["data"]["system_name"] == system:
                status, alerts = c["data"]["status"], c["data"]["alerts"]
            elif c["source"] == "logs" and c["system"] == system:
                logs = c["data"]
        queries.append((system, f"상태={status}. 알림: {' / '.join(alerts)}. 로그: {' / '.join(logs)}"))
    if not queries:
        queries.append((None, state["query"]))
    return queries


async def select_node(state: RunbookAgentState, deps) -> dict:
    selections, seen = [], set()
    for system, text in build_queries(state):
        hits = await deps.retriever.search(text, k=1, mode=deps.config.get("retrieval_mode", "vector"))
        if not hits or hits[0]["score"] < _min_score(deps):
            continue
        hit = hits[0]
        if hit["incident_type"] in seen:
            continue
        seen.add(hit["incident_type"])
        selections.append({"system": system or ", ".join(state["targets"]),
                           "incident_type": hit["incident_type"], "score": hit["score"]})
    selections = selections[:deps.config["max_runbooks"]]
    return {"selections": selections,
            "events": [{"type": "RunbookSelected", "selections": selections}]}


async def fetch_node(state: RunbookAgentState, deps) -> dict:
    if not state["selections"]:
        return {}
    server, template = await deps.mcp.find_resource_template(deps.config["runbook_template_name"])
    collected, events = [], []
    for sel in state["selections"]:
        text = await deps.mcp.read_resource(template.format(incident_type=sel["incident_type"]),
                                            server=server)
        collected.append({"source": "runbook", "system": sel["system"],
                          "incident_type": sel["incident_type"], "data": text})
        events.append({"type": "TaskCompleted", "source": "runbook", "target": sel["incident_type"],
                       "retries": 0})
    return {"collected": collected, "events": events}


def build_runbook_subgraph(deps):
    g = StateGraph(RunbookAgentState)
    g.add_node("select", partial(select_node, deps=deps))
    g.add_node("fetch", partial(fetch_node, deps=deps))
    g.add_edge(START, "select")
    g.add_edge("select", "fetch")
    g.add_edge("fetch", END)
    return g.compile()


@traceable(name="runbook_agent")
async def runbook_agent_node(state: dict, deps, subgraph) -> dict:
    out = await subgraph.ainvoke({"query": state["query"], "targets": state["targets"],
                                  "evidence": state.get("collected", []),
                                  "anomalies": state.get("anomalies", []),
                                  "collected": [], "events": []})
    return {"collected": out.get("collected", []), "runbooks": out["selections"],
            "events": out["events"]}
