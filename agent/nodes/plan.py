"""plan 노드 — 조사 대상 시스템을 정하고 task를 만든다. + clarify 노드(되묻기).

[개선5] Base는 대상 시스템을 못 찾으면 무조건 auth-service로 폴백했다("billing-service가
느려요"에도 auth-service를 조사). 여기서는 아래 순서로 찾고, 끝까지 못 찾으면 추측하지 않고
사용자에게 되묻는다.
  1) 시스템 이름이 그대로 있으면 그것 (explicit)
  2) 기능 별칭("로그인", "결제", "알림")으로 (alias)
  3) "그 서비스", "아까" 같은 후속 질문이면 이전 대화에서 가장 최근 시스템 (history)  ← [추가3]
  4) 그래도 없으면 LLM이 시스템 설명 목록을 보고 판단, 확실하지 않으면 빈 리스트 (llm)
"""
import re

from langsmith import traceable

from ..config import catalog_text, find_system_names, find_systems_by_alias, known_systems

FOLLOW_UP_RE = re.compile(r"그 서비스|그 시스템|그거|아까|방금|이전|같은 서비스|거기|그쪽")


def _from_history(history: list[dict], summary: str) -> list[str]:
    for msg in reversed(history):
        if msg.get("role") == "user" and (found := find_system_names(msg.get("content", ""))):
            return found
    return find_system_names(summary or "")[-1:]


async def resolve_targets(query: str, history: list[dict], summary: str, deps):
    """반환: (targets, source, usage|None)."""
    if found := find_system_names(query):
        return found, "explicit", None
    if found := find_systems_by_alias(query):
        return found, "alias", None
    if FOLLOW_UP_RE.search(query) and (found := _from_history(history, summary)):
        return found, "history", None
    llm_targets, usage = await deps.fast_llm.resolve_systems(query, history, summary, catalog_text())
    valid = [t for t in dict.fromkeys(llm_targets) if t in known_systems()]
    return valid, ("llm" if valid else "none"), usage


@traceable(name="plan_node")
async def plan_node(state: dict, deps) -> dict:
    targets, source, usage = await resolve_targets(
        state["query"], state.get("history", []), state.get("memory_summary", ""), deps)
    cost = usage["usd"] if usage else 0.0
    if not targets:
        return {"route": "clarify", "targets": [], "target_source": "none", "tasks": [],
                "cost_usd": cost,
                "events": [{"type": "PlanCreated", "task_count": 0, "targets": [], "source": "none"}]}
    tasks = [{"id": f"task-{i}", "agent": "research", "kind": "monitoring", "target": t,
              "status": "pending"} for i, t in enumerate(targets)]
    if state.get("needs_analysis"):
        tasks.append({"id": "task-analysis", "agent": "analysis", "kind": "pattern-analysis",
                      "status": "pending"})
    return {"targets": targets, "target_source": source, "tasks": tasks, "cost_usd": cost,
            "events": [{"type": "PlanCreated", "task_count": len(tasks), "targets": targets,
                        "source": source}]}


def after_plan(state: dict) -> str:
    return "clarify" if state.get("route") == "clarify" else "gate"


@traceable(name="clarify_node")
async def clarify_node(state: dict, deps) -> dict:
    unknown = re.findall(r"[a-z][a-z0-9-]*-(?:service|db|proxy|\d+)", state["query"])
    head = (f"'{unknown[0]}'은(는) 모니터링 대상 시스템이 아닙니다. " if unknown else
            "어느 시스템의 문제인지 확인이 필요합니다. ")
    reply = (head + "현재 모니터링 중인 시스템은 " + ", ".join(known_systems()) + "입니다. "
             "시스템 이름이나 증상(예: 로그인 지연, 결제 실패, 알림 지연)을 알려주시면 바로 진단하겠습니다.")
    return {"final": reply, "events": [{"type": "Finalize", "pipeline": "clarify"}]}
