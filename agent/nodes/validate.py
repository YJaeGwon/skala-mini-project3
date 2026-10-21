"""[개선2] validate 노드 — 형식 검사(Base) + 사실 검증(수치·시스템).

불합격이면 사유를 write에 피드백해 재작성시키고, 최대 validate_max_attempts(3)회까지만 시도한다.
3회 모두 불합격이면 수집된 값만 옮겨 적은 안전 답변(templates.py)으로 대체한다 —
Base는 3회째에 '불합격이어도 통과 처리'해서 틀린 초안이 그대로 나갔다.
"""
from langsmith import traceable

from ..templates import fallback_report
from ..validators import run_all


@traceable(name="validate_node")
async def validate_node(state: dict, deps) -> dict:
    attempts = state.get("validation_attempts", 0) + 1
    failures = run_all(state["draft"], targets=state["targets"],
                       collected=state.get("collected", []),
                       min_length=deps.config["validate_min_length"])
    ok = not failures
    give_up = not ok and attempts >= deps.config["validate_max_attempts"]
    out = {"validation_attempts": attempts, "validation_failures": failures,
           "validation_feedback": None if ok or give_up else "\n".join(f"- {f}" for f in failures),
           "used_fallback": give_up}
    if give_up:
        out["draft"] = fallback_report(state.get("collected", []))
    verdict = "합격" if ok else ("불합격(최대 시도 도달 — 안전 답변으로 대체)" if give_up else "불합격")
    out["events"] = [{"type": "Validation", "attempt": attempts, "verdict": verdict,
                      "failures": failures}]
    return out


def after_validate(state: dict) -> str:
    return "write" if state.get("validation_feedback") else "risk_gate"
