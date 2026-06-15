"""DeviceManager：板子注册表 + 在线探测。

port 在 Windows 是 COMx，Linux 是 /dev/...（建议 udev 别名固定，避免 ttyUSBx 漂移）。
探测通过短开串口判断在线；pyserial 通过 backend 注入以便单测替换。
"""
from __future__ import annotations

from typing import Any, Protocol

from ..config import BoardConfig


class SerialOpener(Protocol):
    def __call__(self, port: str, baud: int, timeout: float = 0.2) -> Any: ...


class _RealSerial:
    def __call__(self, port: str, baud: int, timeout: float = 0.2) -> Any:
        import serial

        return serial.Serial(port, baud, timeout=timeout)


class DeviceManager:
    def __init__(self, boards: dict[str, BoardConfig], open_serial: SerialOpener | None = None) -> None:
        self.boards = boards
        self._open = open_serial or _RealSerial()

    def list_boards(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for bid, cfg in self.boards.items():
            out.append(
                {
                    "id": bid,
                    "port": cfg.port,
                    "baud": cfg.baud,
                    "buttons": sorted(cfg.buttons),
                    "power_relay": cfg.power_relay,
                    "online": self.probe(cfg.port, cfg.baud),
                }
            )
        return out

    def probe(self, port: str, baud: int = 115200) -> bool:
        try:
            s = self._open(port, baud)
            s.close()
            return True
        except Exception:
            return False

    def get(self, board_id: str) -> BoardConfig:
        if board_id not in self.boards:
            raise KeyError(f"unknown board {board_id!r}; register it in boards.yaml first")
        return self.boards[board_id]
