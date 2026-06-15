"""真 Jira 客户端：Jira Cloud REST API v2（同步，与 MockJiraClient 协议一致）。

- get_defect：GET /rest/api/2/issue/{key} → 映射成 Defect
- add_comment：POST /rest/api/2/issue/{key}/comment {body: text}
认证：basic auth（email:api_token）。http 层可注入（测试用 fake）。

repro_steps 来自可配置的自定义字段（jira.repro_field）；该字段预期存结构化列表
（每项 {action, target, note}），无则 repro_steps 为空、由 ReproPlanner 从描述推断。
"""
from __future__ import annotations

import base64
import os
from typing import Any, Callable

from .models import Defect, ReproStep

# 注入的同步 http：(method, url, headers, body) → (status_code, json)
HttpFn = Callable[[str, str, dict[str, str], dict[str, Any] | None], tuple[int, dict[str, Any]]]

_PRIO_MAP = {"Highest": "blocker", "High": "critical", "Medium": "major", "Low": "minor", "Lowest": "trivial"}
_VALID_ACTIONS = {"press_button", "power_cycle", "serial_cmd", "wait", "flash"}


def _httpx_request(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    import httpx

    with httpx.Client(timeout=15.0) as c:
        r = c.request(method, url, headers=headers, json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_text": r.text}


def _parse_repro(raw: Any) -> list[ReproStep]:
    """把自定义字段值解析成 ReproStep 列表。支持 [{action,target,note}] 形式。"""
    if not isinstance(raw, list):
        return []
    out: list[ReproStep] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if action not in _VALID_ACTIONS:
            continue
        out.append(ReproStep(action=action, target=str(item.get("target", "")), note=str(item.get("note", ""))))  # type: ignore[arg-type]
    return out


def _map_issue(issue: dict[str, Any], repro_field: str = "") -> Defect:
    fields = issue.get("fields") or {}
    repro_raw = fields.get(repro_field) if repro_field else None
    return Defect(
        id=issue.get("key", ""),
        title=fields.get("summary", "") or "",
        severity=_PRIO_MAP.get((fields.get("priority") or {}).get("name", ""), "major"),
        summary=fields.get("description", "") or "",
        repro_steps=_parse_repro(repro_raw),
    )


class JiraRestClient:
    def __init__(
        self,
        base_url: str,
        email: str = "",
        token: str = "",
        repro_field: str = "",
        http: HttpFn = _httpx_request,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL", "")
        self.token = token or os.getenv("JIRA_TOKEN", "")
        self.repro_field = repro_field
        self._http = http

    def _auth(self) -> dict[str, str]:
        cred = base64.b64encode(f"{self.email}:{self.token}".encode()).decode()
        return {"Authorization": f"Basic {cred}", "Accept": "application/json", "Content-Type": "application/json"}

    def get_defect(self, defect_id: str) -> Defect:
        fields = ["summary", "description", "priority", "status"]
        if self.repro_field:
            fields.append(self.repro_field)
        url = f"{self.base_url}/rest/api/2/issue/{defect_id}?fields={','.join(fields)}"
        code, body = self._http("GET", url, self._auth(), None)
        if code != 200:
            raise RuntimeError(f"jira get {defect_id} failed: {code} {body}")
        return _map_issue(body, self.repro_field)

    def add_comment(self, defect_id: str, body_text: str) -> None:
        url = f"{self.base_url}/rest/api/2/issue/{defect_id}/comment"
        code, body = self._http("POST", url, self._auth(), {"body": body_text})
        if code not in (200, 201):
            raise RuntimeError(f"jira comment {defect_id} failed: {code} {body}")
