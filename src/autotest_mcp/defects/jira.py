"""Jira 客户端：接口与 mock 实现。

初期用 MockJiraClient 读本地 yaml（用户已决定初期 mock，不接公司真实系统）。
接口与真 Jira REST 对齐：get_defect / comment / transition。M2 换真实现即可。
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import yaml

from .models import Defect


class JiraClient(Protocol):
    def get_defect(self, defect_id: str) -> Defect: ...

    def add_comment(self, defect_id: str, body: str) -> None: ...


def make_jira(cfg, defects_override: str | None = None) -> "JiraClient":
    """按 config.jira.backend 选 mock 或 真 Jira REST。defects_override 仅 mock 用。"""
    j = cfg.jira
    if j.backend == "rest":
        from .jira_rest import JiraRestClient

        return JiraRestClient(j.base_url, j.email, j.token, j.repro_field)
    return MockJiraClient(defects_override or j.defects_path)


class MockJiraClient:
    """从 yaml 文件读缺陷库。schema: {defects: [{id, title, ...}]}"""

    def __init__(self, source: str | Path) -> None:
        self.source = Path(source)

    def _load(self) -> dict:
        if not self.source.exists():
            return {"defects": []}
        return yaml.safe_load(self.source.read_text(encoding="utf-8")) or {"defects": []}

    def get_defect(self, defect_id: str) -> Defect:
        data = self._load()
        for raw in data.get("defects", []):
            if raw.get("id") == defect_id:
                return Defect(**raw)
        raise KeyError(f"defect {defect_id!r} not found in {self.source}")

    def list_defect_ids(self) -> list[str]:
        return [d["id"] for d in self._load().get("defects", []) if "id" in d]

    def add_comment(self, defect_id: str, body: str) -> None:
        # mock：把评论追加到 source 旁的 comments 文件，留痕可查
        log = self.source.with_suffix(".comments.txt")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"=== {defect_id} ===\n{body}\n\n")
