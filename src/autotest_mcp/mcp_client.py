"""硬件 MCP client：编排器用它调硬件网关（M0 的 server）。

- HardwareClient 协议：与 M0 暴露的 tool 一一对应。
- McpHardwareClient：经 streamable-http 调远端网关（家用 tailscale / 公司内网）。
- FakeHardwareClient：单测与本地无板运行，模拟 panic 与 capture。

pipeline 只依赖协议，不感知具体实现。
"""
from __future__ import annotations

from typing import Any, Protocol


class HardwareClient(Protocol):
    async def list_boards(self) -> list[dict[str, Any]]: ...

    async def flash(self, board_id: str, bin_or_build_dir: str, baud: int = 921600) -> dict[str, Any]: ...

    async def capture_serial(
        self,
        board_id: str,
        duration_s: float | None = None,
        until_pattern: str | None = None,
        inject: list[str] | None = None,
        baud: int | None = None,
    ) -> dict[str, Any]: ...

    async def press_button(self, board_id: str, button: str, duration_ms: int = 100) -> dict[str, Any]: ...

    async def power_cycle(self, board_id: str, off_delay_s: float = 1.0) -> dict[str, Any]: ...


class McpHardwareClient:
    """经 MCP streamable-http 调硬件网关。token 走 Authorization 头。"""

    def __init__(self, url: str, token: str = "", board_id: str = "boardA") -> None:
        self.url = url
        self.token = token
        self.board_id = board_id

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _call(self, name: str, **args) -> Any:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        async with streamablehttp_client(self.url, headers=self._headers()) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
                return _unwrap(result)

    async def list_boards(self) -> list[dict[str, Any]]:
        return await self._call("list_boards")

    async def flash(self, board_id: str, bin_or_build_dir: str, baud: int = 921600) -> dict[str, Any]:
        return await self._call("flash", board_id=board_id, bin_or_build_dir=bin_or_build_dir, baud=baud)

    async def capture_serial(self, board_id, duration_s=None, until_pattern=None, inject=None, baud=None):
        return await self._call(
            "capture_serial",
            board_id=board_id,
            duration_s=duration_s,
            until_pattern=until_pattern,
            inject=inject,
            baud=baud,
        )

    async def press_button(self, board_id, button, duration_ms=100):
        return await self._call("press_button", board_id=board_id, button=button, duration_ms=duration_ms)

    async def power_cycle(self, board_id, off_delay_s=1.0):
        return await self._call("power_cycle", board_id=board_id, off_delay_s=off_delay_s)


def _unwrap(result: Any) -> Any:
    """MCP call_tool 结果 → python 值。新版返回 (content, structured)。"""
    if isinstance(result, tuple) and len(result) == 2:
        _content, structured = result
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        return structured
    return result


class FakeHardwareClient:
    """无板/无网关时的假硬件。capture 返回假 log；panic 控制是否含 panic（复测时置 False 模拟修复生效）。"""

    def __init__(
        self,
        board_id: str = "boardA",
        fake_log: str | None = None,
        panic: bool = True,
        panic_first_n: int | None = None,
    ) -> None:
        """panic_first_n: 设定后，仅前 N 次 capture 返回 panic（模拟"修复后不再 panic"）。"""
        self.board_id = board_id
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._panic = panic
        self._panic_first_n = panic_first_n
        self._captures = 0
        self._fake_log = fake_log or (
            "ets Jul 29 2019\r\n"
            "I (320) main_task: Started on CPU0\n"
            "I (330) app_main: boot ok\n"
            + ("Guru Meditation Error: Core  0 panic'ed (StoreProhibited)\n"
               "Backtrace:0x42001234 0x42005678 0x42009abc\n" if panic else "LOW_POWER_ENTER\n")
        )

    async def list_boards(self):
        return [{"id": self.board_id, "port": "FAKE", "online": True}]

    async def flash(self, board_id, bin_or_build_dir, baud=921600):
        self.calls.append(("flash", {"board_id": board_id, "bin": bin_or_build_dir}))
        return {"ok": True, "duration_s": 1.2}

    async def capture_serial(self, board_id, duration_s=None, until_pattern=None, inject=None, baud=None):
        self.calls.append(("capture", {"board_id": board_id, "inject": inject}))
        self._captures += 1
        if self._panic_first_n is not None:
            panic = self._captures <= self._panic_first_n
        else:
            panic = self._panic
        text = self._fake_log if panic else "LOW_POWER_ENTER\n"
        return {
            "log_path": f"logs/{board_id}_fake.log",
            "lines": text.count("\n"),
            "panic_detected": "Guru Meditation" in text,
            "matched_pattern": until_pattern if until_pattern and until_pattern in text else None,
            "_text": text,  # 测试用：直接把假 log 文本透出，免去读文件
        }

    async def press_button(self, board_id, button, duration_ms=100):
        self.calls.append(("press", {"board_id": board_id, "button": button}))
        return {"ok": True, "action": "press", "relay": 1}

    async def power_cycle(self, board_id, off_delay_s=1.0):
        self.calls.append(("power_cycle", {"board_id": board_id}))
        return {"ok": True}
