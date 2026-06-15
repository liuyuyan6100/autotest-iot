"""GatewayRegistrar：硬件网关（M0 server 侧）向控制面注册 + 心跳。

http poster 可注入（真用 httpx，测试用 fake），无网络可单测。
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

PostFn = Callable[[str, dict[str, Any], dict[str, str]], Awaitable[dict[str, Any]]]


async def _httpx_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json() if r.content else {}


class GatewayRegistrar:
    def __init__(
        self,
        cp_url: str,
        gw_id: str,
        url: str,
        token: str,
        boards: list[str],
        cp_token: str = "",
        interval: float = 10.0,
        post: PostFn = _httpx_post,
    ) -> None:
        self.cp_url = cp_url.rstrip("/")
        self.gw_id = gw_id
        self.url = url
        self.token = token
        self.boards = list(boards)
        self.interval = interval
        self.cp_token = cp_token
        self._post = post
        self._task: asyncio.Task | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.cp_token:
            h["Authorization"] = f"Bearer {self.cp_token}"
        return h

    async def register(self) -> dict[str, Any]:
        payload = {"url": self.url, "token": self.token, "boards": self.boards}
        res = await self._post(f"{self.cp_url}/gateways/{self.gw_id}/register", payload, self._headers())
        self.calls.append(("register", payload))
        return res

    async def heartbeat(self) -> dict[str, Any]:
        res = await self._post(f"{self.cp_url}/gateways/{self.gw_id}/heartbeat", {}, self._headers())
        self.calls.append(("heartbeat", {}))
        return res

    async def _loop(self) -> None:
        try:
            await self.register()
        except Exception:
            pass
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.heartbeat()
            except Exception:
                pass

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
