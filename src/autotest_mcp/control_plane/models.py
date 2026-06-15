"""控制面数据模型：网关信息 / 作业。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class GatewayInfo:
    id: str
    url: str                       # 控制面访问该网关的 MCP http url
    token: str = ""
    boards: list[str] = field(default_factory=list)
    last_seen: float = 0.0         # monotonic 时间戳

    def owns(self, board: str) -> bool:
        return board in self.boards


@dataclass
class Job:
    id: str
    board: str
    op: str
    args: dict[str, Any] = field(default_factory=dict)
    status: Literal["queued", "running", "done", "failed"] = "queued"
    result: Any = None
    error: str = ""
    gateway_id: str = ""           # 由哪个网关最终执行
    created_at: float = 0.0
