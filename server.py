"""all_total 개선판 — FastAPI 백엔드 (:8100). Base server.py의 구조·응답 형식을 유지하고 확장했다.

- lifespan 싱글턴 (Base Wave 1): build_runtime()으로 MCP 연결·checkpointer·runbook RAG 인덱스·LLM·
  그래프를 프로세스당 1회 만든다.
- /chat, /chat/stream (Base Wave 3): 응답 형식(reply, events, metadata)은 Base와 같고, 아래가 추가됐다.
    status: done | pending_approval   ← [추가1] 위험 조치가 있으면 운영자 승인 대기
    run_id: 승인할 때 쓰는 실행 ID
- /approve ([추가1]): 운영자가 승인·거절하면 멈춘 그래프를 Command(resume=...)로 재개한다.
  checkpointer가 SQLite 파일이라 서버를 재시작해도 대기 건을 승인할 수 있다.
- 대화 이력 (Base Wave 12) + [추가3] 요약 메모리: 그래프의 memory 노드가 처리한다.
- SUPERVISOR_VERSION=v1이면 legacy 선형 파이프라인으로 전환 (Base Wave 14 그대로).
"""
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()   # LANGCHAIN_* / OPENAI_API_KEY — langsmith import보다 먼저

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from pydantic import BaseModel

from agent.bootstrap import build_runtime
from agent.supervisor_v1 import run_v1

CREATION_COUNT = 0


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ApproveRequest(BaseModel):
    run_id: str
    approved: bool
    note: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CREATION_COUNT
    CREATION_COUNT += 1
    backend = os.environ.get("LLM_BACKEND", "fake")
    rt = await build_runtime(
        backend, os.environ.get("SUPERVISOR_VERSION", "v2"),
        checkpoint_path=os.environ.get("CHECKPOINT_DB", "checkpoints.db"),
        mcp_flaky=os.environ.get("MCP_FLAKY", "1") == "1",
        embed_backend=os.environ.get("EMBED_BACKEND") or None,
        session_db=Path(os.environ["SESSION_DB"]) if os.environ.get("SESSION_DB") else None)
    app.state.rt = rt
    app.state.backend = backend
    app.state.instance_id = id(rt.deps)
    app.state.pending = {}
    yield
    await rt.aclose()
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers
        wait_for_all_tracers()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)


def _deps():
    return app.state.rt.deps


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 40}


@app.get("/health")
async def health():
    d = _deps()
    return {"status": "ok", "instance_id": app.state.instance_id, "creation_count": CREATION_COUNT,
            "supervisor_version": d.version, "llm_backend": app.state.backend,
            "fast_llm": d.fast_llm.name, "quality_llm": d.quality_llm.name,
            "embedder": d.retriever.embedder.name, "runbook_chunks": app.state.rt.index_chunks,
            "pending_approvals": len(app.state.pending)}


@app.get("/version")
async def version():
    return {"supervisor_version": _deps().version}


@app.get("/pending")
async def pending():
    return app.state.pending


def _metadata(result: dict, run_id: str, started: float, langsmith_run_id=None) -> dict:
    """Base 메타데이터 키를 그대로 두고 과제1 항목을 덧붙였다."""
    return {
        "route": result.get("route"),
        "task_count": len(result.get("tasks", [])),
        "gate_removed": result.get("gate_removed", 0),
        "replan_rounds": 0,
        "retry_count": result.get("retry_count", 0),
        "validation_attempts": result.get("validation_attempts", 0),
        "cost_usd": round(result.get("cost_usd", 0.0), 6),
        "llm_backend": app.state.backend,
        "supervisor_version": _deps().version,
        "instance_id": app.state.instance_id,
        "langsmith_run_id": langsmith_run_id,
        # ── 과제1 추가 ──
        "targets": result.get("targets"), "target_source": result.get("target_source"),
        "runbooks": result.get("runbooks"), "risky_actions": result.get("risky_actions"),
        "approval": result.get("approval"), "used_fallback": result.get("used_fallback", False),
        "memory_summary": bool(result.get("memory_summary")),
        "latency_s": round(time.perf_counter() - started, 3), "run_id": run_id,
    }


def _finish(thread_id: str, run_id: str, result: dict, started: float, ls_id=None) -> dict:
    store = _deps().session_store
    if "__interrupt__" in result:
        approval = result["__interrupt__"][0].value
        app.state.pending[run_id] = {"thread_id": thread_id, "approval": approval}
        reply = ("답변에 서비스 중단 위험이 있는 조치가 포함되어 운영자 승인을 기다리고 있습니다: "
                 + " / ".join(approval.get("risky_actions", [])[:3]))
        store.append(thread_id, "assistant", f"[운영자 승인 대기] {reply}")
        return {"status": "pending_approval", "run_id": run_id, "reply": reply, "approval": approval,
                "events": result.get("events", []), "metadata": _metadata(result, run_id, started, ls_id)}
    app.state.pending.pop(run_id, None)
    store.append(thread_id, "assistant", result["final"])
    return {"status": "done", "run_id": run_id, "reply": result["final"],
            "events": result.get("events", []), "metadata": _metadata(result, run_id, started, ls_id)}


def _new_run(thread_id: str, message: str) -> tuple[str, list[dict]]:
    store = _deps().session_store
    history = store.load(thread_id)
    store.append(thread_id, "user", message)
    return f"{thread_id}:{uuid.uuid4().hex[:8]}", history


@traceable(name="chat_request")
async def _handle_chat(message: str, thread_id: str) -> dict:
    started = time.perf_counter()
    run_id, history = _new_run(thread_id, message)
    rt = get_current_run_tree()
    ls_id = str(rt.id) if rt else None
    if _deps().version != "v2":
        result = await run_v1(_deps(), message, thread_id, history)
        return _finish(thread_id, run_id, result, started, ls_id)
    result = await app.state.rt.graph.ainvoke(
        {"query": message, "thread_id": thread_id, "run_id": run_id, "history": history},
        _config(run_id))
    return _finish(thread_id, run_id, result, started, ls_id)


@app.post("/chat")
async def chat(req: ChatRequest):
    return await _handle_chat(req.message, req.thread_id)


@app.post("/approve")
@traceable(name="approve_request")
async def approve(req: ApproveRequest):
    graph, started = app.state.rt.graph, time.perf_counter()
    if graph is None:
        raise HTTPException(400, "v1에는 승인 단계가 없습니다")
    snapshot = await graph.aget_state(_config(req.run_id))
    if not snapshot.next:
        raise HTTPException(409, f"승인 대기 중인 실행이 아닙니다: {req.run_id}")
    result = await graph.ainvoke(Command(resume={"approved": req.approved, "note": req.note}),
                                 _config(req.run_id))
    thread_id = snapshot.values.get("thread_id") or req.run_id.split(":")[0]
    return _finish(thread_id, req.run_id, result, started)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class _Interrupt:
    def __init__(self, value):
        self.value = value


@app.get("/chat/stream")
async def chat_stream(message: str, thread_id: str = "default"):
    """노드 진행 상황(updates)과 답변 토큰(custom)을 SSE로 보낸다.
    events는 reducer라서 노드 업데이트마다 그 노드가 새로 만든 이벤트만 들어 있다
    (Base의 seen 인덱스 로직이 필요 없어졌다)."""

    async def gen():
        started = time.perf_counter()
        run_id, history = _new_run(thread_id, message)
        if _deps().version != "v2":
            result = await run_v1(_deps(), message, thread_id, history)
            for ev in result["events"]:
                yield _sse(ev)
            out = _finish(thread_id, run_id, result, started)
            yield _sse({"type": "FinalAnswer", "reply": out["reply"], "metadata": out["metadata"]})
            yield "data: [DONE]\n\n"
            return
        final, last_prompt, interrupted = "", None, None
        async for mode, payload in app.state.rt.graph.astream(
                {"query": message, "thread_id": thread_id, "run_id": run_id, "history": history},
                _config(run_id), stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield _sse(payload)
                continue
            for node_name, delta in payload.items():
                if node_name == "__interrupt__":
                    interrupted = delta[0].value
                    continue
                for ev in (delta or {}).get("events") or []:
                    yield _sse({**ev, "node": node_name})
                if (delta or {}).get("final"):
                    final = delta["final"]
                if (delta or {}).get("last_prompt"):
                    last_prompt = delta["last_prompt"]
        state = (await app.state.rt.graph.aget_state(_config(run_id))).values
        if interrupted:
            out = _finish(thread_id, run_id, {**state, "__interrupt__": [_Interrupt(interrupted)]}, started)
            yield _sse({"type": "PendingApproval", "run_id": run_id, "approval": interrupted,
                        "reply": out["reply"]})
        else:
            out = _finish(thread_id, run_id, {**state, "final": final}, started)
            yield _sse({"type": "FinalAnswer", "reply": final, "prompt": last_prompt,
                        "metadata": out["metadata"]})
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8100")), log_level="warning")
