"""SerialMonitor：抓 UART → 落盘带时间戳日志，监听 panic，支持注入串口命令。

阻塞式实现（pyserial 是同步的）；server 层用 asyncio.to_thread 调用，避免阻塞事件循环。
停止条件：duration_s 超时 或 命中 until_pattern；两者都缺时默认抓 5 秒。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

PANIC_PATTERNS = ("Guru Meditation", "abort()", "Backtrace:", "Core  panic", "panic handler")
DEFAULT_DURATION = 5.0


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s) or "board"


class _FakeTime:
    """可注入的时钟，便于单测加速。"""

    def __init__(self) -> None:
        self._t = 0.0

    def monotonic(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt

    def sleep(self, dt: float) -> None:  # 单测里不真睡
        self._t += dt


def capture(
    port: str,
    baud: int = 115200,
    duration_s: float | None = None,
    until_pattern: str | None = None,
    inject: list[str] | None = None,
    log_dir: str = "logs",
    *,
    open_serial: Any = None,
    sleep: Any = None,
    monotonic: Any = None,
    board_id: str = "board",
) -> dict[str, Any]:
    import serial  # 局部导入，避免无硬件环境 import 失败

    if duration_s is None and until_pattern is None:
        duration_s = DEFAULT_DURATION

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ts = int((monotonic or time.monotonic)() * 1000) if monotonic else int(time.time() * 1000)
    log_path = Path(log_dir) / f"{_safe_name(board_id)}_{ts}.log"

    open_serial = open_serial or (lambda p, b, **kw: serial.Serial(p, b, timeout=0.1))
    _sleep = sleep or time.sleep
    _now = monotonic or time.monotonic

    matched: str | None = None
    panic = False
    line_count = 0

    ser = open_serial(port, baud)
    try:
        if inject:
            for line in inject:
                ser.write((line.rstrip("\n") + "\n").encode("utf-8"))
            if hasattr(ser, "flush"):
                ser.flush()
        start = _now()
        with open(log_path, "w", encoding="utf-8") as f:
            while True:
                data = ser.read(4096)
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if data:
                    f.write(data)
                    f.flush()
                    line_count += data.count("\n")
                    if until_pattern and until_pattern in data:
                        matched = until_pattern
                        break
                    if any(p in data for p in PANIC_PATTERNS):
                        panic = True
                if duration_s is not None and (_now() - start) >= duration_s:
                    break
                _sleep(0.01)
    finally:
        try:
            ser.close()
        except Exception:
            pass

    return {
        "log_path": str(log_path),
        "lines": line_count,
        "panic_detected": panic,
        "matched_pattern": matched,
    }
