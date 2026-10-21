"""analysis 노드 — Base Wave 6 보완 그대로: gate가 살려둔 analysis task가 있을 때만 여러 시스템을 비교 분석.
개선: 모니터링뿐 아니라 로그도 함께 넘긴다."""
from langsmith import traceable


@traceable(name="analysis_node")
async def analysis_node(state: dict, deps) -> dict:
    pending = [t for t in state["tasks"] if t["agent"] == "analysis" and t["status"] == "pending"]
    if not pending:
        return {"events": [{"type": "AnalysisSkipped", "reason": "analysis task 0개"}]}
    summary, usage = await deps.fast_llm.analyze(state.get("collected", []))
    tasks = [dict(t, status="done") if t["agent"] == "analysis" else t for t in state["tasks"]]
    return {"tasks": tasks, "collected": [{"source": "analysis", "data": summary}],
            "cost_usd": usage["usd"],
            "events": [{"type": "AnalysisCompleted", "length": len(summary)}]}
