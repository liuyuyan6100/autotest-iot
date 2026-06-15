"""板级并发锁：同一块板的触板动作互斥，避免两个 agent 同时烧/抓串口。

策略：
- queue（默认）：后来的调用排队等待锁释放。
- reject：锁被占时立即抛 BoardBusy，让 client 自己决定重试。

仅治理单网关内的并发；跨网关/分布式的资源调度是 M2 控制面的职责。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class BoardBusy(Exception):
    """板子正被占用（reject 策略下抛出）。"""


class BoardLocks:
    def __init__(self, policy: str = "queue") -> None:
        self._policy = policy
        self._locks: dict[str, asyncio.Lock] = {}

    def _get(self, board_id: str) -> asyncio.Lock:
        if board_id not in self._locks:
            self._locks[board_id] = asyncio.Lock()
        return self._locks[board_id]

    @asynccontextmanager
    async def acquire(self, board_id: str) -> AsyncIterator[None]:
        lock = self._get(board_id)
        if self._policy == "reject" and lock.locked():
            raise BoardBusy(f"board {board_id!r} is busy")
        async with lock:
            yield
