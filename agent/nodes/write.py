"""write 노드 — quality 모델로 대응 보고 작성 (토큰 스트리밍).

표준 진단 절차는 MCP Prompt에서 가져온다(Base와 같음, 프롬프트 이름은 설정에서 읽음).
검증 반려나 승인 거절이 있으면 그 사유를 feedback으로 받아 다시 쓴다.
"""
from langgraph.config import get_stream_writer
from langsmith import traceable


@traceable(name="write_node")
async def write_node(state: dict, deps) -> dict:
    attempt = state.get("validation_attempts", 0) + 1
    prompt_name = deps.config["prompt_name"]
    server = await deps.mcp.find_prompt(prompt_name)
    procedure = await deps.mcp.get_prompt(
        prompt_name, {"system_name": ", ".join(state["targets"]), "symptom": state["query"]},
        server=server)
    writer = get_stream_writer()
    draft, usage = await deps.quality_llm.write(
        state["query"], state.get("collected", []), procedure, attempt,
        state.get("validation_feedback"),
        on_token=lambda piece: writer({"type": "AnswerToken", "attempt": attempt, "delta": piece}))
    return {"draft": draft, "last_prompt": usage.get("prompt"), "cost_usd": usage["usd"],
            "events": [{"type": "DraftWritten", "attempt": attempt, "length": len(draft)}]}
