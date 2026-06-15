"""JobQueue：硬件请求在网关离线时排队，上线后续跑。

按板分组；每条 Job 有状态。counter 可注入便于确定性 id。
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .models import Job


class JobQueue:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._jobs: list[Job] = []
        self._seq = 0

    def enqueue(self, board: str, op: str, args: dict[str, Any] | None = None) -> Job:
        self._seq += 1
        job = Job(
            id=f"job-{self._seq:04d}",
            board=board,
            op=op,
            args=dict(args or {}),
            status="queued",
            created_at=self._clock(),
        )
        self._jobs.append(job)
        return job

    def pending(self, board: str) -> list[Job]:
        return [j for j in self._jobs if j.board == board and j.status == "queued"]

    def get(self, job_id: str) -> Job | None:
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None

    def all(self) -> list[Job]:
        return list(self._jobs)

    def mark(self, job_id: str, status: str, result: Any = None, error: str = "", gateway_id: str = "") -> None:
        j = self.get(job_id)
        if j is None:
            return
        j.status = status  # type: ignore[assignment]
        j.result = result
        j.error = error
        j.gateway_id = gateway_id
