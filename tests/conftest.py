"""테스트 공통 fixture — MCP subprocess·네트워크 없이 같은 그래프를 만든다 (의존성 주입).

- FakeMCP: mcp_server.py와 같은 인터페이스, 같은 data/ 파일. 지표에 랜덤 jitter를 넣지 않는다.
- StubRetriever: 검색 품질과 무관하게 그래프 로직만 검증하려고 알림 키워드로 runbook을 고르는 스텁.
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.bootstrap import build_runtime  # noqa: E402
from agent.config import DATA_DIR, systems  # noqa: E402


class FakeMCP:
    def __init__(self):
        self.calls: list[str] = []
        self.flaky = False

    async def call_tool(self, name, arguments, server="ops"):
        self.calls.append(name)
        if self.flaky and name == "get_monitoring_status":
            self.flaky = False
            raise asyncio.TimeoutError("simulated")
        s = arguments["system_name"]
        if name == "get_monitoring_status":
            d = systems().get(s)
            if d is None:
                return {"system_name": s, "status": "unknown", "cpu_percent": 0.0,
                        "memory_percent": 0.0, "last_checked": "", "alerts": []}
            return {"system_name": s, "status": d["status"], "cpu_percent": d["cpu_base"],
                    "memory_percent": d["memory_base"], "alerts": d["alerts"],
                    "last_checked": datetime.now().isoformat()}
        if name == "get_recent_logs":
            lines = json.loads((DATA_DIR / "logs.json").read_text()).get(s)
            return {"system_name": s, "found": lines is not None, "lines": lines or []}
        raise ValueError(name)

    async def find_resource_template(self, name):
        return "ops", "runbook://incident-response/{incident_type}"

    async def read_resource(self, uri, server):
        self.calls.append("read_resource")
        return (DATA_DIR / "runbooks" / f"{uri.rsplit('/', 1)[1]}.md").read_text()

    async def find_prompt(self, name):
        return "ops"

    async def get_prompt(self, name, arguments, server="ops"):
        return f"시스템: {arguments['system_name']}\n증상: {arguments['symptom']}\n1. 상태 조회 2. 로그 3. runbook"


KEYWORDS = [("latency", "high-latency"), ("cpu", "cpu-spike"), ("memory", "memory-leak"),
            ("timeout", "network-timeout"), ("disk", "disk-full"), ("refused", "db-down"),
            ("consumer lag", "queue-backlog"), ("certificate", "cert-expiry")]


class StubRetriever:
    def __init__(self, real):
        self.embedder = real.embedder
        self.titles = real.titles

    async def search(self, text, k=3, mode="vector"):
        low = text.lower()
        for kw, t in KEYWORDS:
            if kw in low:
                return [{"incident_type": t, "title": self.titles[t], "score": 0.9}]
        return [{"incident_type": "db-down", "title": self.titles["db-down"], "score": 0.01}]


@pytest.fixture
def fake_mcp():
    return FakeMCP()


@pytest.fixture
async def runtime(tmp_path, fake_mcp):
    rt = await build_runtime("fake", "v2", mcp=fake_mcp, index_root=tmp_path / "vectordb",
                             session_db=tmp_path / "session.db")
    rt.deps.retriever = StubRetriever(rt.deps.retriever)
    yield rt
    await rt.aclose()
