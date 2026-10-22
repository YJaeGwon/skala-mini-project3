"""[추가1] Human-in-the-loop — 위험 조치가 든 답변은 사용자 승인 후에만 내보낸다.

risk_gate: 검증을 통과한 답변에서 위험 조치(재시작·롤백·failover 등, data/risk_policy.json)를
  '실행하라'는 문장을 찾는다 ("재시작 반복 여부 확인" 같은 점검 문장은 제외).
  - 없으면 그대로 finalize
  - 있고 아직 승인 전이면 human_approval로
  - 승인이 거절돼 다시 썼는데도 남아 있으면 그 문장만 지우고 finalize
human_approval: interrupt()로 그래프를 멈춘다. 상태는 checkpointer(SQLite)에 저장되고,
  사용자가 /approve로 승인·거절하면 Command(resume=...)로 재개된다.
  ⚠️ 재개되면 이 노드가 '처음부터 다시' 실행되므로 interrupt() 앞에 부작용을 두지 않는다.

PDF 예시는 write와 validate 사이에 승인 노드를 두지만, 여기서는 validate 뒤에 뒀다 — 검증 반려로
재작성될 때마다 승인을 다시 받는 일을 막고, 사용자가 '검증을 통과한 최종본'을 승인하게 하기 위해서다.
"""
from langgraph.types import interrupt
from langsmith import traceable

from ..config import risk_policy
from ..validators import find_risky, strip_risky


@traceable(name="risk_gate_node")
async def risk_gate_node(state: dict, deps) -> dict:
    risky = find_risky(state["draft"], risk_policy())
    approval = state.get("approval")
    if risky and approval and not approval.get("approved"):
        draft = strip_risky(state["draft"], risk_policy())
        return {"draft": draft, "risky_actions": [],
                "events": [{"type": "RiskyActionsRemoved", "count": len(risky)}]}
    return {"risky_actions": risky, "events": [{"type": "RiskChecked", "risky": len(risky)}]}


def after_risk_gate(state: dict) -> str:
    return "human_approval" if state.get("risky_actions") and not state.get("approval") else "finalize"


@traceable(name="human_approval_node")
async def human_approval_node(state: dict, deps) -> dict:
    value = interrupt({"type": "ApprovalRequired", "run_id": state.get("run_id"),
                       "targets": state.get("targets", []),
                       "risky_actions": state.get("risky_actions", []),
                       "draft": state.get("draft", "")})
    approval = {"approved": bool((value or {}).get("approved")), "note": (value or {}).get("note", "")}
    out = {"approval": approval, "events": [{"type": "ApprovalResolved", **approval}]}
    if not approval["approved"]:
        # 거절 → 위험 조치를 뺀 안전한 대안으로 다시 쓰게 한다 (검증 횟수는 새로 센다)
        actions = "; ".join(state.get("risky_actions", []))
        out.update(validation_attempts=0, validation_feedback=(
            f"- 사용자가 다음 위험 조치를 승인하지 않았습니다: {actions}\n"
            "- 재시작·롤백·failover 같은 조치를 빼고, 모니터링 강화·원인 분석·임시 완화책 같은 "
            "안전한 대안으로 다시 작성하세요." + (f"\n- 사용자 메모: {approval['note']}" if approval["note"] else "")))
    return out


def after_approval(state: dict) -> str:
    return "finalize" if state["approval"]["approved"] else "write"
