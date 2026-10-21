"""Base retry.py 회귀 테스트 — Timeout만 재시도, 그 외 에러는 즉시 전파."""
import asyncio

import pytest

from agent.retry import with_retry


async def test_retry_then_success():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.TimeoutError
        return "ok"

    assert await with_retry(flaky, base_delay=0.01) == ("ok", 1)


async def test_permanent_error_not_retried():
    async def broken():
        raise ValueError

    with pytest.raises(ValueError):
        await with_retry(broken, base_delay=0.01)
