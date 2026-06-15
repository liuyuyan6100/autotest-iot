"""autotest MCP 网关入口：注册所有 tool，按配置启动 http/stdio。

铁律：所有"执行"在此层；智能体（未来 agent）只调用这些 tool。
触板动作（flash / capture_serial / press_button / power_cycle）持板级锁，防并发冲突。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import transport
from .concurrency import BoardBusy, BoardLocks
from .config import AppConfig, EnvSettings, load_config
from .tools.builder import build as build_fw
from .tools.device import DeviceManager
from .tools.flasher import flash as flash_fw
from .tools.hardware import HardwareController, MockRelayBackend
from .tools.serial_mon import capture as capture_serial_impl
from .tools.symbolizer import find_addr2line, symbolize as symbolize_impl


@dataclass
class Context:
    config: AppConfig
    devices: DeviceManager
    locks: BoardLocks
    hardware: HardwareController


def _to_thread(fn, *args, **kwargs):
    return asyncio.to_thread(fn, *args, **kwargs)


def build_server(cfg: AppConfig) -> tuple[FastMCP, Context]:
    mcp = FastMCP("autotest-mcp")
    devices = DeviceManager(cfg.boards)
    locks = BoardLocks(cfg.server.board_lock_policy)
    hardware = HardwareController(MockRelayBackend())
    ctx = Context(config=cfg, devices=devices, locks=locks, hardware=hardware)

    @mcp.tool()
    def list_boards() -> list[dict[str, Any]]:
        """列出已注册板子及在线状态。"""
        return devices.list_boards()

    @mcp.tool()
    def symbolize(elf_path: str, text: str) -> dict[str, Any]:
        """把 panic backtrace 文本里的地址还原成 函数+文件:行。"""
        return symbolize_impl(elf_path, text, addr2line=find_addr2line(cfg.tools.addr2line))

    @mcp.tool()
    async def build(source_dir: str, idf_version: str | None = None, target: str = "esp32s3") -> dict[str, Any]:
        """编译固件（docker espressif/idf 或 local idf.py）。"""
        return await _to_thread(
            build_fw,
            source_dir,
            idf_version or cfg.tools.idf_version,
            target,
            cfg.tools.builder_backend,
        )

    @mcp.tool()
    async def flash(board_id: str, bin_or_build_dir: str, baud: int = 921600) -> dict[str, Any]:
        """烧录指定板子：传 .bin 或含 flash_args 的 build 目录。占用板级锁。"""
        try:
            async with locks.acquire(board_id):
                board = devices.get(board_id)
                return await _to_thread(flash_fw, board.port, baud, bin_or_build_dir)
        except BoardBusy as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def capture_serial(
        board_id: str,
        duration_s: float | None = None,
        until_pattern: str | None = None,
        inject: list[str] | None = None,
        baud: int | None = None,
    ) -> dict[str, Any]:
        """抓串口日志落盘，监听 panic；可注入串口命令。占用板级锁。"""
        try:
            async with locks.acquire(board_id):
                board = devices.get(board_id)
                return await _to_thread(
                    capture_serial_impl,
                    board.port,
                    baud or board.baud,
                    duration_s,
                    until_pattern,
                    inject,
                    "logs",
                    board_id=board_id,
                )
        except BoardBusy as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def press_button(board_id: str, button: str, duration_ms: int = 100) -> dict[str, Any]:
        """按压物理按键（经继电器）。占用板级锁。"""
        try:
            async with locks.acquire(board_id):
                board = devices.get(board_id)
                if button not in board.buttons:
                    return {"ok": False, "error": f"button {button!r} not configured on {board_id}"}
                return await _to_thread(hardware.press_button, board.buttons[button].relay, duration_ms)
        except BoardBusy as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    async def power_cycle(board_id: str, off_delay_s: float = 1.0) -> dict[str, Any]:
        """对板子断电再上电（经继电器）。占用板级锁。"""
        try:
            async with locks.acquire(board_id):
                board = devices.get(board_id)
                if board.power_relay is None:
                    return {"ok": False, "error": f"board {board_id} has no power_relay configured"}
                return await _to_thread(hardware.power_cycle, board.power_relay, off_delay_s)
        except BoardBusy as e:
            return {"ok": False, "error": str(e)}

    return mcp, ctx


def main() -> None:
    env = EnvSettings()
    cfg = load_config(env.config_path)
    if env.token:
        cfg.server.token = env.token  # 环境变量覆盖 yaml

    mcp, _ = build_server(cfg)

    if cfg.server.transport == "stdio":
        mcp.run(transport="stdio")
        return

    app = transport.build_http_app(mcp, cfg.server.token)
    transport.run_http(app, cfg.server.host, cfg.server.port, cfg.server.mtls)


if __name__ == "__main__":
    main()
