"""[추가4] 로그 서브에이전트 (compiled subgraph): fetch → filter

- fetch : 대상 시스템들의 get_recent_logs(MCP Tool, 과제1에서 추가)를 병렬 호출
- filter: ERROR/WARN/FATAL 줄만 남긴다(없으면 원문 유지) — 답변 근거와 runbook 검색 질의에 쓴다
Base에는 로그 데이터 자체가 없었다(data/logs.json 추가).
"""
import asyncio
import re
from functools import partial

from langgraph.graph import END, START, StateGraph
from langsmith import traceable

from ..retry import with_retry
from ..state import LogAgentState as _LogState

LEVEL_RE = re.compile(r"\b(ERROR|WARN|FATAL)\b")


async def fetch_node(state: _LogState, deps) -> dict:
    async def one(system):
        data, _ = await with_retry(deps.mcp.call_tool, "get_recent_logs", {"system_name": system})
        return data

    return {"raw": list(await asyncio.gather(*(one(s) for s in state["targets"])))}


async def filter_node(state: _LogState, deps) -> dict:
    collected, events = [], []
    for item in state["raw"]:
        if not item.get("found"):
            continue
        important = [line for line in item["lines"] if LEVEL_RE.search(line)] or item["lines"]
        collected.append({"source": "logs", "system": item["system_name"], "data": important})
        events.append({"type": "TaskCompleted", "source": "logs", "target": item["system_name"],
                       "lines": len(important)})
    return {"collected": collected, "events": events}


def build_log_subgraph(deps):
    g = StateGraph(_LogState)
    g.add_node("fetch", partial(fetch_node, deps=deps))
    g.add_node("filter", partial(filter_node, deps=deps))
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "filter")
    g.add_edge("filter", END)
    return g.compile()


@traceable(name="log_agent")
async def log_agent_node(state: dict, deps, subgraph) -> dict:
    out = await subgraph.ainvoke({"targets": state["targets"], "collected": [], "events": []})
    return {"collected": out["collected"], "events": out["events"]}
