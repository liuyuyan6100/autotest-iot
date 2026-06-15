"""飞书审批门测试：_parse_status、FakeGate、driver(approved→closed / rejected→rejected / timeout)、LarkApprovalGate http 注入。"""
import asyncio

import pytest
from langgraph.types import Command

from autotest_mcp.feishu.driver import await_approval_and_resume
from autotest_mcp.feishu.gate import FakeApprovalGate, LarkApprovalGate, _parse_status
from autotest_mcp.feishu import FakeApprovalGate as FAG
from autotest_mcp.defects.jira import MockJiraClient
from autotest_mcp.git_client import FakeGitClient
from autotest_mcp.knowledge.store import FileKnowledgeStore
from autotest_mcp.mcp_client import FakeHardwareClient
from autotest_mcp.orchestrator import Deps, build_orchestrator
from autotest_mcp.testing import FakeLLM


def test_parse_status_string_and_int():
    assert _parse_status({"data": {"status": "APPROVED"}}) == "approved"
    assert _parse_status({"status": "REJECTED"}) == "rejected"
    assert _parse_status({"data": {"status": 2}}) == "approved"
    assert _parse_status({"data": {"status": 1}}) == "pending"
    assert _parse_status({"data": {"status": 4}}) == "canceled"


def _deps(tmp_path, *, auto_approve=False):
    src = tmp_path / "fw" / "components/button"
    src.mkdir(parents=True, exist_ok=True)
    (src / "button.c").write_text("void fire(void){ handle->cb(ev); }\n")
    return Deps(
        llm=FakeLLM(), hardware=FakeHardwareClient("boardA", panic_first_n=1), git=FakeGitClient(),
        knowledge=FileKnowledgeStore(tmp_path / "kb.json"),
        jira=MockJiraClient("config/defects.example.yaml"),
        repo_dir=str(tmp_path / "fw"),
        whitelist=["test> "], build_fn=lambda s: {"ok": True, "build_dir": s},
        auto_approve=auto_approve,
    )


@pytest.mark.asyncio
async def test_driver_approved_resumes_to_closed(tmp_path):
    deps = _deps(tmp_path)  # auto_approve=False → 停在 gate
    graph = build_orchestrator(deps, max_attempts=2)
    cfg = {"configurable": {"thread_id": "f1"}}
    await graph.ainvoke({"defect_id": "BUG-123"}, cfg)
    assert "human_gate" in graph.get_state(cfg).next

    decision = await await_approval_and_resume(
        graph, cfg, FakeApprovalGate("approved"),
        title="t", content="c", approver="ou_x",
        poll_interval=0.0, timeout=10.0,
    )
    assert decision == "approved"
    final = graph.get_state(cfg).values
    assert final["verdict"] == "closed"
    assert final["approved"] is True


@pytest.mark.asyncio
async def test_driver_rejected_routes_to_rejected_terminal(tmp_path):
    deps = _deps(tmp_path)
    graph = build_orchestrator(deps, max_attempts=2)
    cfg = {"configurable": {"thread_id": "f2"}}
    await graph.ainvoke({"defect_id": "BUG-123"}, cfg)

    decision = await await_approval_and_resume(
        graph, cfg, FakeApprovalGate("rejected"),
        title="t", content="c", approver="ou_x",
        poll_interval=0.0, timeout=10.0,
    )
    assert decision == "rejected"
    final = graph.get_state(cfg).values
    assert final["verdict"] == "rejected"
    assert final["approved"] is False


@pytest.mark.asyncio
async def test_driver_timeout(tmp_path):
    deps = _deps(tmp_path)
    graph = build_orchestrator(deps, max_attempts=2)
    cfg = {"configurable": {"thread_id": "f3"}}
    await graph.ainvoke({"defect_id": "BUG-123"}, cfg)

    # clock 固定不动 → 永远 pending 但 timeout 立刻到期
    t = [0.0]

    async def bump(_d):
        t[0] += 100

    decision = await await_approval_and_resume(
        graph, cfg, FakeApprovalGate("pending"),
        title="t", content="c", approver="ou_x",
        poll_interval=0.0, timeout=1.0,
        clock=lambda: t[0], sleep=bump,
    )
    assert decision == "timeout"
    assert graph.get_state(cfg).values["approved"] is False


@pytest.mark.asyncio
async def test_lark_gate_with_injected_http():
    calls = []

    async def fake_http(method, path, headers, body):
        calls.append((method, path))
        if "tenant_access_token" in path:
            return 200, {"tenant_access_token": "TOK"}
        if method == "POST" and path.endswith("/approval/v3/instances"):
            return 200, {"code": 0, "data": {"instance_code": "INST-1"}}
        if method == "GET":
            return 200, {"code": 0, "data": {"status": "APPROVED"}}
        return 500, {}

    gate = LarkApprovalGate("APPROVAL_CODE", "aid", "asec", http=fake_http)
    code = await gate.create("title", "content", "ou_x")
    assert code == "INST-1"
    assert await gate.status(code) == "approved"
    # token 缓存：第二次 status 不再换 token（仍含一次 token 调用 + 一次 get）
    token_calls = [c for c in calls if "tenant_access_token" in c[1]]
    assert len(token_calls) == 1
