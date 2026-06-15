"""飞书审批门：把 LangGraph 人工门换成飞书审批实例（通过/拒绝）。

- ApprovalGate 协议：create(title, content, approver) → instance_code；status(code) → 状态。
- LarkApprovalGate：走 Feishu OpenAPI v3（POST /approval/v3/instances 建、GET .../instances/{code} 查），
  tenant_access_token 用 app_id/app_secret 换取；http 层可注入（测试用 fake）。
- FakeApprovalGate：测试/无飞书时用，按脚本返回结果。

真实 create 需要 user 在飞书后台定义审批流程（approval_code）+ app 凭据；这部分在用户机器跑，
逻辑在此用 fake 全测。
"""
from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable, Literal, Protocol

GateStatus = Literal["pending", "approved", "rejected", "canceled", "error"]

# 注入的 http：method/path/headers/json → (status_code, response_json)
HttpFn = Callable[[str, str, dict[str, str], dict[str, Any] | None], Awaitable[tuple[int, dict[str, Any]]]]


async def _httpx_request(method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    import httpx

    url = path if path.startswith("http") else f"https://open.feishu.cn/open-apis{path}"
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.request(method, url, headers=headers, json=body)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_text": r.text}


def _parse_status(data: dict[str, Any]) -> GateStatus:
    """把 instances/get 返回的 data 映射成标准状态。兼容字符串与整数编码。"""
    raw = (data.get("data") or data).get("status")
    if isinstance(raw, str):
        s = raw.upper()
        return {"APPROVED": "approved", "PASSED": "approved"}.get(s, s.lower()) if s in {"APPROVED", "PASSED"} else s.lower()  # type: ignore[return-value]
    if isinstance(raw, int):
        # 飞书常见整数编码：2=通过 3=拒绝 4=已撤回 1/10/11=审批中
        return {2: "approved", 3: "rejected", 4: "canceled"}.get(raw, "pending")  # type: ignore[return-value]
    return "pending"


class ApprovalGate(Protocol):
    async def create(self, title: str, content: str, approver: str) -> str: ...

    async def status(self, instance_code: str) -> GateStatus: ...


class LarkApprovalGate:
    def __init__(
        self,
        approval_code: str,
        app_id: str = "",
        app_secret: str = "",
        base: str = "https://open.feishu.cn/open-apis",
        http: HttpFn = _httpx_request,
    ) -> None:
        self.approval_code = approval_code
        self.app_id = app_id or os.getenv("LARK_APP_ID", "")
        self.app_secret = app_secret or os.getenv("LARK_APP_SECRET", "")
        self.base = base.rstrip("/")
        self._http = http
        self._token: str = ""

    async def _tenant_token(self) -> str:
        if self._token:
            return self._token
        code, body = await self._http(
            "POST", f"{self.base}/auth/v3/tenant_access_token/internal", {}, {"app_id": self.app_id, "app_secret": self.app_secret}
        )
        self._token = body.get("tenant_access_token", "")
        return self._token

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def create(self, title: str, content: str, approver: str) -> str:
        token = await self._tenant_token()
        form = json.dumps(
            [
                {"control": "input", "id": "FieldText", "value": {"text": title}},
                {"control": "textarea", "id": "FieldDesc", "value": {"text": content}},
            ],
            ensure_ascii=False,
        )
        body = {
            "approval_code": self.approval_code,
            "form": form,
            "open_id": approver or None,  # 发起人；审批人由审批流程节点决定
        }
        code, resp = await self._http("POST", f"{self.base}/approval/v3/instances", self._auth_headers(token), body)
        if code != 200 or resp.get("code") not in (0, None):
            raise RuntimeError(f"create approval failed: {resp}")
        return resp["data"]["instance_code"]

    async def status(self, instance_code: str) -> GateStatus:
        token = await self._tenant_token()
        code, resp = await self._http("GET", f"{self.base}/approval/v3/instances/{instance_code}", self._auth_headers(token), None)
        if code != 200 or resp.get("code") not in (0, None):
            return "error"
        return _parse_status(resp)


class FakeApprovalGate:
    """脚本化结果：outcomes 是状态序列，用完停在最后一个；或固定 outcome。"""

    def __init__(self, outcome: GateStatus | list[GateStatus] = "approved") -> None:
        self._seq = [outcome] if isinstance(outcome, str) else list(outcome)
        self._idx = 0
        self.created: list[tuple[str, str, str]] = []

    async def create(self, title: str, content: str, approver: str) -> str:
        import itertools

        code = f"inst-{len(self.created) + 1}"
        self.created.append((title, content, approver))
        return code

    async def status(self, instance_code: str) -> GateStatus:
        if self._idx < len(self._seq) - 1:
            self._idx += 1
            return "pending"
        return self._seq[-1]
