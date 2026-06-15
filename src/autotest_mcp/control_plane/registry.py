"""Registry：硬件网关注册表 + 心跳 + TTL 上下线判定 + 按板定位在线网关。

clock 可注入（测试用假时钟）；不依赖网络。
"""
from __future__ import annotations

import time
from typing import Callable

from .models import GatewayInfo


class Registry:
    def __init__(self, ttl: float = 30.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl
        self._clock = clock
        self._gateways: dict[str, GatewayInfo] = {}

    def register(self, gw_id: str, url: str, token: str, boards: list[str]) -> GatewayInfo:
        gw = GatewayInfo(id=gw_id, url=url, token=token, boards=list(boards), last_seen=self._clock())
        self._gateways[gw_id] = gw
        return gw

    def heartbeat(self, gw_id: str) -> GatewayInfo | None:
        gw = self._gateways.get(gw_id)
        if gw is None:
            return None
        gw.last_seen = self._clock()
        return gw

    def unregister(self, gw_id: str) -> None:
        self._gateways.pop(gw_id, None)

    def is_online(self, gw: GatewayInfo) -> bool:
        return (self._clock() - gw.last_seen) <= self.ttl

    def list(self) -> list[GatewayInfo]:
        return list(self._gateways.values())

    def online_gateways(self) -> list[GatewayInfo]:
        return [g for g in self._gateways.values() if self.is_online(g)]

    def gateway_for_board(self, board: str) -> GatewayInfo | None:
        """返回拥有该板且在线的网关；多个时取最近心跳的。"""
        candidates = [g for g in self.online_gateways() if g.owns(board)]
        if not candidates:
            return None
        return max(candidates, key=lambda g: g.last_seen)
