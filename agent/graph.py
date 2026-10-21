"""v2 Supervisor 그래프 — 조립만 담당한다. [개선4] 모듈화: 노드 로직은 agent/nodes/*.py.

Base는 노드 9개·규칙·라우팅 함수가 이 파일 하나(338줄)에 모여 있었다.

memory → route ─┬─ chat ─────────────→ chat_answer → END
                └─ incident → plan ─┬─ 대상 불명 → clarify → END
                                    └─ gate → research_supervisor ─┬─ metric_agent ─┐ (병렬)
                                                                   └─ log_agent ────┴→ runbook_agent
runbook_agent → analysis → write → validate ─┬─ 불합격(3회 미만) → write
                                             └─ 합격/대체 → risk_gate ─┬─ 위험 조치 → human_approval ─┬─ 승인 → finalize
                                                                       │                             └─ 거절 → write
                                                                       └─ 없음 ─────────────────────────────→ finalize → END
"""
from functools import partial

from langgraph.graph import END, START, StateGraph

from .deps import SupervisorDeps
from .nodes.analysis import analysis_node
from .nodes.chat_answer import chat_answer_node
from .nodes.finalize import finalize_node
from .nodes.gate import gate_node
from .nodes.log_agent import build_log_subgraph, log_agent_node
from .nodes.memory import memory_node
from .nodes.metric_agent import build_metric_subgraph, metric_agent_node
from .nodes.plan import after_plan, clarify_node, plan_node
from .nodes.research_supervisor import research_supervisor_node
from .nodes.risk_gate import after_approval, after_risk_gate, human_approval_node, risk_gate_node
from .nodes.route import after_route, route_node
from .nodes.runbook_agent import build_runbook_subgraph, runbook_agent_node
from .nodes.validate import after_validate, validate_node
from .nodes.write import write_node
from .state import AgentState


def build_graph(deps: SupervisorDeps, checkpointer=None):
    g = StateGraph(AgentState)
    node = lambda fn: partial(fn, deps=deps)   # Base Wave 13 — 명시적 의존성 주입
    g.add_node("memory", node(memory_node))
    g.add_node("route", node(route_node))
    g.add_node("chat_answer", node(chat_answer_node))
    g.add_node("plan", node(plan_node))
    g.add_node("clarify", node(clarify_node))
    g.add_node("gate", node(gate_node))
    g.add_node("research_supervisor", node(research_supervisor_node))
    g.add_node("metric_agent", partial(metric_agent_node, deps=deps,
                                       subgraph=build_metric_subgraph(deps)))
    g.add_node("log_agent", partial(log_agent_node, deps=deps, subgraph=build_log_subgraph(deps)))
    g.add_node("runbook_agent", partial(runbook_agent_node, deps=deps,
                                        subgraph=build_runbook_subgraph(deps)))
    g.add_node("analysis", node(analysis_node))
    g.add_node("write", node(write_node))
    g.add_node("validate", node(validate_node))
    g.add_node("risk_gate", node(risk_gate_node))
    g.add_node("human_approval", node(human_approval_node))
    g.add_node("finalize", node(finalize_node))

    g.add_edge(START, "memory")
    g.add_edge("memory", "route")
    g.add_conditional_edges("route", after_route, ["chat_answer", "plan"])
    g.add_edge("chat_answer", END)
    g.add_conditional_edges("plan", after_plan, ["clarify", "gate"])
    g.add_edge("clarify", END)
    g.add_edge("gate", "research_supervisor")
    g.add_edge("research_supervisor", "metric_agent")      # 메트릭·로그 에이전트 병렬 실행
    g.add_edge("research_supervisor", "log_agent")
    g.add_edge("metric_agent", "runbook_agent")            # 둘 다 끝나면 runbook 에이전트 1회 실행
    g.add_edge("log_agent", "runbook_agent")
    g.add_edge("runbook_agent", "analysis")
    g.add_edge("analysis", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", after_validate, ["write", "risk_gate"])
    g.add_conditional_edges("risk_gate", after_risk_gate, ["human_approval", "finalize"])
    g.add_conditional_edges("human_approval", after_approval, ["finalize", "write"])
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
