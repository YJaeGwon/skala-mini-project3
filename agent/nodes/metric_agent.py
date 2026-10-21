"""[개선3] 메트릭 서브에이전트 (compiled subgraph): collect → detect

- collect: 대상 시스템들의 get_monitoring_status(MCP Tool)를 병렬 호출, Timeout이면 재시도(Base retry.py)
- detect : 상태가 healthy가 아닌 시스템을 '이상 시스템'으로 표시 → runbook_agent가 이 시스템들의 runbook을 찾는다

[개선5] Base research_node에 있던 '태스크당 고정 지연 0.35초(asyncio.sleep)'는 병렬 효과를
보여주기 위한 인위적 지연이라 제거했다.
"""
import asyncio
import time
from functools import partial

from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from ..retry import with_retry
from ..state import MetricAgentState


async def collect_node(state: MetricAgentState, deps) -> dict:
    async def one(system):
        data, retries = await with_retry(deps.mcp.call_tool, "get_monitoring_status",
                                         {"system_name": system})
        return system, data, retries

    started = time.perf_counter()
    results = await asyncio.gather(*(one(s) for s in state["targets"]))
    elapsed = round(time.perf_counter() - started, 3)
    return {"collected": [{"source": "monitoring", "data": d} for _, d, _ in results],
            "retry_count": sum(r for *_, r in results),
            "events": [{"type": "TaskCompleted", "source": "monitoring", "target": s, "retries": r}
                       for s, _, r in results] + [{"type": "MetricsCollected", "elapsed": elapsed}]}


async def detect_node(state: MetricAgentState, deps) -> dict:
    anomalies = [c["data"]["system_name"] for c in state["collected"]
                 if c["source"] == "monitoring" and c["data"]["status"] != "healthy"]
    return {"anomalies": anomalies, "events": [{"type": "AnomaliesDetected", "systems": anomalies}]}


def build_metric_subgraph(deps):
    g = StateGraph(MetricAgentState)
    g.add_node("collect", partial(collect_node, deps=deps))
    g.add_node("detect", partial(detect_node, deps=deps))
    g.add_edge(START, "collect")
    g.add_edge("collect", "detect")
    g.add_edge("detect", END)
    return g.compile()


@traceable(name="metric_agent")
async def metric_agent_node(state: dict, deps, subgraph) -> dict:
    """wrapper: 서브그래프를 새 입력으로 호출한다 — 부모 events/collected를 그대로 넘기면
    reducer(operator.add) 때문에 결과가 중복되기 때문."""
    out = await subgraph.ainvoke({"targets": state["targets"], "collected": [], "events": [],
                                  "retry_count": 0})
    return {"collected": out["collected"], "anomalies": out["anomalies"],
            "retry_count": out["retry_count"], "events": out["events"]}
