import asyncio

import pytest

from autotest_mcp.concurrency import BoardBusy, BoardLocks


@pytest.mark.asyncio
async def test_queue_serializes():
    locks = BoardLocks("queue")
    order = []

    async def worker(name, delay):
        async with locks.acquire("boardA"):
            order.append(("start", name))
            await asyncio.sleep(delay)
            order.append(("end", name))

    await asyncio.gather(worker("a", 0.01), worker("b", 0.01))
    # 两个 worker 完整嵌套，不交错
    assert order == [("start", "a"), ("end", "a"), ("start", "b"), ("end", "b")] or order == [
        ("start", "b"), ("end", "b"), ("start", "a"), ("end", "a"),
    ]


@pytest.mark.asyncio
async def test_reject_when_busy():
    locks = BoardLocks("reject")
    held = asyncio.Event()

    async def holder():
        async with locks.acquire("boardA"):
            held.set()
            await asyncio.sleep(0.05)

    h = asyncio.create_task(holder())
    await held.wait()
    with pytest.raises(BoardBusy):
        async with locks.acquire("boardA"):
            pass
    await h


@pytest.mark.asyncio
async def test_released_then_available():
    locks = BoardLocks("reject")
    async with locks.acquire("b"):
        pass
    # 锁释放后可再次获取
    async with locks.acquire("b"):
        pass
