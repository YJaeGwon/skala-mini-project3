"""gate 노드 — Base Wave 6 권위 게이트 그대로: needs_analysis=False인데 섞인 analysis task를 코드로 제거."""
from langsmith import traceable


@traceable(name="gate_node")
async def gate_node(state: dict, deps) -> dict:
    tasks = state["tasks"]
    if not state.get("needs_analysis", False):
        kept = [t for t in tasks if t["agent"] != "analysis"]
    else:
        kept = tasks
    removed = len(tasks) - len(kept)
    return {"tasks": kept, "gate_removed": removed,
            "events": [{"type": "GateApplied", "removed_analysis_tasks": removed}]}
