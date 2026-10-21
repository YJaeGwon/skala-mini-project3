"""route 노드 — 잡담(chat)과 장애(incident)를 나눈다 (Base Wave 5).

개선: LLM 판단 뒤에 코드 보정을 한 번 더 한다 — 메시지에 시스템 이름이나 별칭이 있으면
장애 문의로 본다. 이전 대화 요약도 함께 넘겨 "그 서비스는요?" 같은 후속 질문을 알아보게 했다.
"""
from langsmith import traceable

from ..config import find_system_names, find_systems_by_alias


@traceable(name="route_node")
async def route_node(state: dict, deps) -> dict:
    result, usage = await deps.fast_llm.route(state["query"], state.get("history", []),
                                              state.get("memory_summary", ""))
    route = result["route"]
    if find_system_names(state["query"]) or find_systems_by_alias(state["query"]):
        route = "incident"
    event = {"type": "RouteDecided", "route": route}
    return {"route": route, "needs_analysis": result["needs_analysis"], "cost_usd": usage["usd"],
            "events": [event]}


def after_route(state: dict) -> str:
    return "chat_answer" if state["route"] == "chat" else "plan"
