"""HardwareController：继电器控制的物理动作（按键 / 控电）。

RelayBackend 抽象继电器硬件：
- MockRelayBackend：打印动作，无真继电器时用（M0 默认）。
- CliRelayBackend：shell 出可配置命令模板，对接将来真实 USB 继电器。

set(channel, on=True)：on=True = 闭合电路（按键短接 / 通电）；on=False = 断开。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Protocol


class RelayBackend(Protocol):
    def set(self, channel: int, on: bool) -> None: ...


class MockRelayBackend:
    """仅记录动作，不操作真实硬件。"""

    def __init__(self) -> None:
        self.actions: list[tuple[int, bool]] = []

    def set(self, channel: int, on: bool) -> None:
        self.actions.append((channel, on))


class CliRelayBackend:
    """按命令模板执行：{channel} 和 {state}（on/off）会被替换。"""

    def __init__(self, on_template: str, off_template: str, run: Callable[..., Any] = __import__("subprocess").run) -> None:
        self.on_template = on_template
        self.off_template = off_template
        self._run = run

    def set(self, channel: int, on: bool) -> None:
        tmpl = self.on_template if on else self.off_template
        cmd = tmpl.format(channel=channel, state="on" if on else "off")
        self._run(cmd, shell=True, check=True)


class HardwareController:
    def __init__(self, backend: RelayBackend, sleep: Callable[[float], None] = time.sleep) -> None:
        self.backend = backend
        self._sleep = sleep

    def press_button(self, relay: int, duration_ms: int = 100) -> dict[str, Any]:
        self.backend.set(relay, on=True)
        self._sleep(duration_ms / 1000.0)
        self.backend.set(relay, on=False)
        return {"action": "press", "relay": relay, "duration_ms": duration_ms}

    def power_cycle(self, relay: int, off_delay_s: float = 1.0) -> dict[str, Any]:
        self.backend.set(relay, on=False)  # 断电
        self._sleep(off_delay_s)
        self.backend.set(relay, on=True)  # 重新上电
        return {"action": "power_cycle", "relay": relay, "off_delay_s": off_delay_s}
