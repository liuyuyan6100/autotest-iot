"""编排状态机测试：一次通过 / 重试后通过 / 超限转人工 / 人工门 interrupt+resume。"""
import asyncio

import pytest
from langgraph.types import Command

from autotest_mcp.defects.jira import MockJiraClient
from autotest_mcp.git_client import FakeGitClient
from autotest_mcp.knowledge.store import FileKnowledgeStore
from autotest_mcp.mcp_client import FakeHardwareClient
from autotest_mcp.orchestrator import Deps, build_orchestrator
from autotest_mcp.testing import FakeLLM


class ScriptedHardware(FakeHardwareClient):
    """前 fail_n 次 capture 返回 panic，之后返回正常（模拟"重试后修复生效"）。"""

    def __init__(self, fail_n: int) -> None:
        self._captures = 0
        self._fail_n = fail_n
        super().__init__(panic=True)

    async def capture_serial(self, board_id, duration_s=None, until_pattern=None, inject=None, baud=None):
        self._captures += 1
        panic = self._captures <= self._fail_n
        log = (
            "Guru Meditation Error: StoreProhibited\nBacktrace:0x42001234\n" if panic else "LOW_POWER_ENTER\n"
        )
        return {
            "log_path": f"logs/{board_id}_scripted.log",
            "lines": log.count("\n"),
            "panic_detected": panic,
            "matched_pattern": None,
        }


def _deps(tmp_path, hardware, *, auto_approve=True, kb=True, max_attempts=2):
    # 种一个含已知 old_string 的源文件，让 Fixer 的 patch 能落地
    src = tmp_path / "fw" / "components/button"
    src.mkdir(parents=True, exist_ok=True)
    (src / "button.c").write_text("void fire(void){ handle->cb(ev); }\n")
    return Deps(
        llm=FakeLLM(), hardware=hardware, git=FakeGitClient(),
        knowledge=FileKnowledgeStore(tmp_path / "kb.json") if kb else None,
        jira=MockJiraClient("config/defects.example.yaml"),
        repo_dir=str(tmp_path / "fw"),
        whitelist=["test> ", "log> ", "repro> "],
        build_fn=lambda s: {"ok": True, "build_dir": s},
        auto_approve=auto_approve,
    ), max_attempts


@pytest.mark.asyncio
async def test_pass_first_try(tmp_path):
    deps, mx = _deps(tmp_path, FakeHardwareClient(panic=False))
    graph = build_orchestrator(deps, max_attempts=mx)
    final = await graph.ainvoke({"defect_id": "BUG-123"}, {"configurable": {"thread_id": "t1"}})
    assert final["verdict"] == "closed"
    assert final["attempt"] == 1
    assert final["case_id"]  # 沉淀


@pytest.mark.asyncio
async def test_retry_then_pass(tmp_path):
    # ScriptedHardware 计所有 capture：M1 占 #1(panic)，复测1=#2(panic→失败)，复测2=#3(通过)
    # 即"复测失败一次后通过"，触发一次回退重试
    deps, mx = _deps(tmp_path, ScriptedHardware(fail_n=2), max_attempts=2)
    graph = build_orchestrator(deps, max_attempts=mx)
    final = await graph.ainvoke({"defect_id": "BUG-123"}, {"configurable": {"thread_id": "t2"}})
    assert final["verdict"] == "closed"
    assert final["attempt"] == 2  # 重试了一次


@pytest.mark.asyncio
async def test_escalate_after_max(tmp_path):
    # 始终失败，重试耗尽 → 转人工
    deps, mx = _deps(tmp_path, ScriptedHardware(fail_n=99), max_attempts=2)
    graph = build_orchestrator(deps, max_attempts=mx)
    final = await graph.ainvoke({"defect_id": "BUG-123"}, {"configurable": {"thread_id": "t3"}})
    assert final["verdict"] == "escalated"
    assert final["attempt"] == 2


@pytest.mark.asyncio
async def test_human_gate_interrupts_then_resume(tmp_path):
    deps, mx = _deps(tmp_path, FakeHardwareClient(panic=False), auto_approve=False)
    graph = build_orchestrator(deps, max_attempts=mx)
    cfg = {"configurable": {"thread_id": "t4"}}
    await graph.ainvoke({"defect_id": "BUG-123"}, cfg)
    state = graph.get_state(cfg)
    # 停在人工门
    assert state.next and "human_gate" in state.next
    # resume 后走到 closed
    final = await graph.ainvoke(Command(resume=True), cfg)
    assert final["verdict"] == "closed"
