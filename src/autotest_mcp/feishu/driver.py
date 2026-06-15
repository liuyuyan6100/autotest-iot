"""审批门 driver：LangGraph 在 human_gate(interrupt) 暂停后，创建飞书审批并轮询，
按结果用 Command(resume=approved) 续跑（通过→True，拒绝/超时→False）。

clock/sleep 可注入，便于单测加速。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from langgraph.types import Command

from .gate import ApprovalGate


async def await_approval_and_resume(
    graph: Any,
    cfg: dict,
    gate: ApprovalGate,
    *,
    title: str,
    content: str,
    approver: str,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> str:
    """创建审批 → 轮询状态 → resume 编排。返回 'approved' | 'rejected' | 'canceled' | 'timeout'。"""
    instance_code = await gate.create(title, content, approver)
    deadline = clock() + timeout
    while clock() < deadline:
        st = await gate.status(instance_code)
        if st == "approved":
            await graph.ainvoke(Command(resume=True), cfg)
            return "approved"
        if st in ("rejected", "canceled"):
            await graph.ainvoke(Command(resume=False), cfg)
            return st
        await sleep(poll_interval)
    await graph.ainvoke(Command(resume=False), cfg)
    return "timeout"
