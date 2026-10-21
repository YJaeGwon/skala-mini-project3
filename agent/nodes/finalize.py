"""finalize 노드 — 최종 답변 확정."""
from langsmith import traceable


@traceable(name="finalize_node")
async def finalize_node(state: dict, deps) -> dict:
    events = [{"type": "ValidationFallback"}] if state.get("used_fallback") else []
    return {"final": state["draft"], "events": events + [{"type": "Finalize", "pipeline": "incident-v2"}]}
