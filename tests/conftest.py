"""共享测试桩。"""
from __future__ import annotations

from typing import Any


class FakeSerial:
    """模拟串口：按预设 chunk 吐数据，记录写入。"""

    def __init__(self, chunks: list[bytes], *_a, **_kw) -> None:
        self._chunks = list(chunks)
        self.written: list[bytes] = []

    def read(self, _n: int = 4096) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def flush(self) -> None:  # noqa: B027
        pass

    def close(self) -> None:  # noqa: B027
        pass


class FakeClock:
    """每次调用推进 step 秒，驱动 capture 循环到 duration 终止。"""

    def __init__(self, step: float = 0.5) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t

    @staticmethod
    def nosleep(_dt: float) -> None:
        pass


class CompletedProcessStub:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def make_run_stub(stdout: str = "", stderr: str = "", returncode: int = 0, record: list | None = None):
    """返回一个假的 subprocess.run，可选记录被调命令。"""

    def _run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if record is not None:
            record.append(cmd)
        return CompletedProcessStub(stdout, stderr, returncode)

    return _run


async def drive_asgi(app: Any, headers: list[tuple[str, str]] | None, method: str = "GET") -> tuple[int, dict]:
    """极简 ASGI 驱动：发一个请求，收 status + body。"""
    import json

    scope = {
        "type": "http",
        "method": method,
        "path": "/mcp",
        "headers": [(k.encode(), v.encode()) for k, v in (headers or [])],
    }

    sent: dict[str, Any] = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
        elif message["type"] == "http.response.body":
            try:
                sent["body"] = json.loads(message["body"])
            except Exception:
                sent["body"] = message["body"].decode("utf-8", "replace")

    await app(scope, receive, send)
    return sent.get("status", 0), sent.get("body", {})
