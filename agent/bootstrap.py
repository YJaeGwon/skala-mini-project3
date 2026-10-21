"""런타임 조립 — server.py(lifespan)와 테스트가 같은 함수로 의존성을 만든다 (의존성 주입).

MCP 연결, checkpointer(HITL), runbook RAG 인덱스, LLM, 세션 저장소를 만들어 SupervisorDeps로
묶고 그래프를 컴파일한다. 테스트는 mcp=FakeMCP, index_root=임시 폴더를 넘긴다.
"""
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from .config import agent_config
from .deps import SupervisorDeps
from .graph import build_graph
from .llm import build_llms
from .mcp_client import MCPClient
from .rag.embeddings import build_embedder
from .rag.index import INDEX_ROOT, ensure_index
from .rag.retriever import RunbookRetriever
from .session_store import SqliteSessionStore


@dataclass
class Runtime:
    deps: SupervisorDeps
    graph: Any
    stack: AsyncExitStack
    index_chunks: int

    async def aclose(self):
        await self.stack.aclose()


async def build_runtime(backend: str, version: str = "v2", *, checkpoint_path: str | None = None,
                        mcp_flaky: bool = True, mcp: Any = None, index_root: Path | None = None,
                        session_db: Path | None = None, embed_backend: str | None = None,
                        config_overrides: dict | None = None) -> Runtime:
    stack = AsyncExitStack()
    if mcp is None:
        mcp = MCPClient(flaky_first_tool_call=mcp_flaky)
        await mcp.start()
        stack.push_async_callback(mcp.stop)
    if checkpoint_path:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(checkpoint_path))
    else:
        checkpointer = InMemorySaver()
    embedder = build_embedder(embed_backend or backend)
    collection, chunks, titles, _ = await ensure_index(embedder, index_root=index_root or INDEX_ROOT)
    fast, quality, judge = build_llms(backend)
    store = SqliteSessionStore(session_db) if session_db else SqliteSessionStore()
    stack.callback(store.close)
    deps = SupervisorDeps(fast_llm=fast, quality_llm=quality, mcp=mcp, session_store=store,
                          version=version, retriever=RunbookRetriever(collection, embedder, chunks, titles),
                          judge_llm=judge, config={**agent_config(), **(config_overrides or {})},
                          backend=embed_backend or backend)
    graph = build_graph(deps, checkpointer) if version == "v2" else None
    return Runtime(deps=deps, graph=graph, stack=stack, index_chunks=len(chunks))
