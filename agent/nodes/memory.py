"""[추가3] 메모리 노드 — 대화가 길어지면 오래된 대화를 LLM으로 요약해 압축한다.

Base는 마지막 10개 메시지(history[-10:])만 프롬프트에 넣어서, 그보다 앞에서 말한 정보
(예: 사용자 이름)는 잊었다. 여기서는 메시지가 memory_max_messages(10)개를 넘으면 최근
memory_keep_recent(6)개만 원문으로 두고 그 앞은 요약해서 SQLite에 저장한다. 이미 요약한
부분은 다시 요약하지 않는다(covered 카운트) — 매 요청마다 요약 비용이 들지 않게.
"""
from langsmith import traceable


@traceable(name="memory_node")
async def memory_node(state: dict, deps) -> dict:
    history = state.get("history", [])
    thread_id = state.get("thread_id", "default")
    max_messages = deps.config["memory_max_messages"]
    keep = deps.config["memory_keep_recent"]
    summary, covered = deps.session_store.load_summary(thread_id)
    if len(history) <= max_messages:
        return {"history": history, "memory_summary": summary}
    older = history[:-keep]
    out = {"history": history[-keep:], "memory_summary": summary}
    if len(older) > covered:
        summary, usage = await deps.fast_llm.summarize(summary, older[covered:])
        deps.session_store.save_summary(thread_id, summary, len(older))
        out.update(memory_summary=summary, cost_usd=usage["usd"],
                   events=[{"type": "MemoryCompressed", "summarized": len(older), "kept": keep}])
    return out
