"""잡담 경로 — 무거운 파이프라인 없이 바로 답한다 (Base Wave 5). [추가3] 대화 요약을 함께 넘긴다."""
from langgraph.config import get_stream_writer
from langsmith import traceable


@traceable(name="chat_answer_node")
async def chat_answer_node(state: dict, deps) -> dict:
    writer = get_stream_writer()
    reply, usage = await deps.fast_llm.chat(
        state["query"], state.get("history", []), state.get("memory_summary", ""),
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece}))
    return {"final": reply, "last_prompt": usage.get("prompt"), "cost_usd": usage["usd"],
            "events": [{"type": "Finalize", "pipeline": "chat-direct"}]}
