"""v2 그래프 전체 흐름 (fake LLM + FakeMCP + StubRetriever + InMemorySaver)."""
from langgraph.types import Command


def cfg(run_id):
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 40}


async def invoke(rt, query, run_id, history=None):
    return await rt.graph.ainvoke({"query": query, "history": history or [], "thread_id": run_id,
                                   "run_id": run_id}, cfg(run_id))


def types(res):
    return [e["type"] for e in res["events"]]


async def test_chat_route(runtime, fake_mcp):
    res = await invoke(runtime, "안녕, 너는 누구야?", "c1")
    assert res["route"] == "chat" and not fake_mcp.calls


async def test_unknown_system_asks_back(runtime, fake_mcp):
    """[개선5] Base는 auth-service로 폴백해 엉뚱한 시스템을 진단했다."""
    res = await invoke(runtime, "billing-service 응답이 느려요", "c2")
    assert res["route"] == "clarify" and "billing-service" in res["final"]
    assert "get_monitoring_status" not in fake_mcp.calls


async def test_incident_pipeline(runtime):
    res = await invoke(runtime, "payments-service 결제 응답이 느려지고 CPU가 치솟았어요", "c3")
    sources = {c["source"] for c in res["collected"]}
    assert {"monitoring", "logs", "runbook"} <= sources
    assert [r["incident_type"] for r in res["runbooks"]] == ["cpu-spike"]
    assert res["validation_attempts"] == 2 and "1)" in res["final"]      # fake 1차 초안은 반려됨
    assert types(res).count("RunbookSelected") == 1                       # 병렬 후 runbook 에이전트 1회


async def test_multi_incident_gets_multiple_runbooks(runtime):
    """[개선1] Base는 cpu-spike 하나만 가져왔다."""
    res = await invoke(runtime, "gateway-service에서 payments-service로 가는 요청이 타임아웃 나고 있어요", "c4")
    assert {r["incident_type"] for r in res["runbooks"]} == {"network-timeout", "cpu-spike"}


async def test_risky_action_needs_approval_then_approve(runtime):
    res = await invoke(runtime, "cache-service 메모리가 90% 근처예요", "c5")
    assert "__interrupt__" in res
    assert any("재시작" in a for a in res["__interrupt__"][0].value["risky_actions"])
    res = await runtime.graph.ainvoke(Command(resume={"approved": True}), cfg("c5"))
    assert res["approval"]["approved"] and "재시작" in res["final"]


async def test_risky_action_rejected_is_removed(runtime):
    await invoke(runtime, "cache-service 메모리가 90% 근처예요", "c6")
    res = await runtime.graph.ainvoke(Command(resume={"approved": False}), cfg("c6"))
    assert "즉시 재시작" not in res["final"] and "승인이 거절" in res["final"]


async def test_follow_up_uses_history(runtime):
    """[추가3] Base는 이전 대화를 보지 않아 auth-service로 폴백했다."""
    history = [{"role": "user", "content": "payments-service CPU가 높아요"},
               {"role": "assistant", "content": "확인했습니다"}]
    res = await invoke(runtime, "그 서비스 최근 로그도 봐줄래요?", "c7", history)
    assert res["targets"] == ["payments-service"] and res["target_source"] == "history"


async def test_memory_summary_keeps_name(runtime):
    """[추가3] Base(history[-10:])는 11번째 이전 메시지의 이름을 잊었다."""
    history = [{"role": "user", "content": "제 이름은 민수입니다"}, {"role": "assistant", "content": "반가워요"}]
    for i in range(6):
        history += [{"role": "user", "content": f"잡담 {i}"}, {"role": "assistant", "content": "네"}]
    res = await invoke(runtime, "제 이름이 뭐였죠?", "c8")
    assert "민수" not in res["final"]                              # 이력 없이 물으면 모름
    res = await runtime.graph.ainvoke({"query": "제 이름이 뭐였죠?", "history": history,
                                       "thread_id": "mem", "run_id": "c9"}, cfg("c9"))
    assert "민수" in res["final"] and "MemoryCompressed" in types(res)
    assert len(res["history"]) == runtime.deps.config["memory_keep_recent"]


async def test_retry_on_flaky_mcp(runtime, fake_mcp):
    fake_mcp.flaky = True
    res = await invoke(runtime, "log-service 디스크 공간이 부족하대요", "c10")
    assert res["retry_count"] == 1 and res["runbooks"][0]["incident_type"] == "disk-full"


async def test_memory_summary_accumulates(runtime):
    """[추가3] 요약을 갱신할 때 이전 요약을 덮어쓰지 않고 이어 붙인다 (실측 버그: 두 번째 요약부터
    첫 사실이 사라져 '휴가 요일'을 잊었다 → 기존 요약을 summarize에 넘기고, 프롬프트로 유지를 강제)."""
    store = runtime.deps.session_store
    history = [{"role": "user", "content": "저 다음 주 목요일부터 휴가예요"}, {"role": "assistant", "content": "네"}]
    for i in range(5):
        history += [{"role": "user", "content": f"잡담 {i}"}, {"role": "assistant", "content": "네"}]
    await runtime.graph.ainvoke({"query": "안녕", "history": history, "thread_id": "acc", "run_id": "a1"}, cfg("a1"))
    history += [{"role": "user", "content": f"추가 잡담 {i}"} for i in range(4)]
    await runtime.graph.ainvoke({"query": "안녕", "history": history, "thread_id": "acc", "run_id": "a2"}, cfg("a2"))
    summary, covered = store.load_summary("acc")
    assert "목요일" in summary and covered == len(history) - runtime.deps.config["memory_keep_recent"]
