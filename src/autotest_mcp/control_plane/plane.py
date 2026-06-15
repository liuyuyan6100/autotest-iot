"""ControlPlane：唯一入口。把硬件请求路由到在线网关；离线则入队，网关上线后续跑。

- registry：网关注册/心跳/上下线
- queue：离线请求排队
- make_client：把 GatewayInfo 变成可调用的 HardwareClient（默认 McpHardwareClient，测试注入 Fake）
硬件 op 走网关；symbolize 等 logic-bound op 留给控制面自己（不在本类路由）。
"""
from __future__ import annotations

from typing import Any, Callable

from ..mcp_client import HardwareClient, McpHardwareClient
from .models import GatewayInfo, Job
from .queue import JobQueue
from .registry import Registry

# 硬件 op → HardwareClient 方法名
_HW_OPS = {
    "list_boards", "flash", "capture_serial", "press_button", "power_cycle",
}


def _default_client_factory(gw: GatewayInfo) -> HardwareClient:
    return McpHardwareClient(gw.url, gw.token)


class ControlPlane:
    def __init__(
        self,
        registry: Registry | None = None,
        queue: JobQueue | None = None,
        make_client: Callable[[GatewayInfo], HardwareClient] = _default_client_factory,
    ) -> None:
        self.registry = registry or Registry()
        self.queue = queue or JobQueue()
        self.make_client = make_client

    # —— 网关管理 ——
    def register_gateway(self, gw_id: str, url: str, token: str, boards: list[str]) -> GatewayInfo:
        return self.registry.register(gw_id, url, token, boards)

    def heartbeat(self, gw_id: str) -> GatewayInfo | None:
        gw = self.registry.heartbeat(gw_id)
        # 心跳使网关恢复在线时，触发该网关所拥有板子的排队作业续跑（best-effort）
        if gw is not None:
            for board in gw.boards:
                if self.queue.pending(board):
                    break  # 标记需要 drain；实际执行在 drain_pending（避免在心跳里阻塞）
        return gw

    def list_gateways(self) -> list[dict[str, Any]]:
        return [
            {
                "id": g.id,
                "url": g.url,
                "boards": g.boards,
                "online": self.registry.is_online(g),
                "last_seen": g.last_seen,
            }
            for g in self.registry.list()
        ]

    # —— 路由 ——
    async def call_hardware(self, board: str, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        args = args or {}
        if op not in _HW_OPS:
            return {"ok": False, "error": f"unknown hardware op: {op}"}
        gw = self.registry.gateway_for_board(board)
        if gw is None:
            job = self.queue.enqueue(board, op, args)
            return {"queued": True, "job_id": job.id, "reason": "no online gateway for board"}
        try:
            result = await self._dispatch(gw, op, args)
            return {"queued": False, "gateway_id": gw.id, "result": result}
        except Exception as exc:  # 网关调用失败 → 入队等重试
            job = self.queue.enqueue(board, op, args)
            return {"queued": True, "job_id": job.id, "reason": f"gateway error: {exc}"}

    async def _dispatch(self, gw: GatewayInfo, op: str, args: dict[str, Any]) -> Any:
        client = self.make_client(gw)
        method = getattr(client, op)
        return await method(**args)

    # —— 离线作业续跑 ——
    async def drain_pending(self, gw_id: str) -> list[Job]:
        """网关上线后，把它所拥有板子的排队作业执行掉。"""
        gw = next((g for g in self.registry.list() if g.id == gw_id), None)
        if gw is None or not self.registry.is_online(gw):
            return []
        done: list[Job] = []
        for board in gw.boards:
            for job in self.queue.pending(board):
                self.queue.mark(job.id, "running", gateway_id=gw.id)
                try:
                    result = await self._dispatch(gw, job.op, job.args)
                    self.queue.mark(job.id, "done", result=result, gateway_id=gw.id)
                except Exception as exc:
                    self.queue.mark(job.id, "failed", error=str(exc), gateway_id=gw.id)
                done.append(self.queue.get(job.id))  # type: ignore[arg-type]
        return done
