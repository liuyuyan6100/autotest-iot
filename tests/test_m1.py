import asyncio

import pytest

from autotest_mcp.agents.repro_planner import filter_whitelist, plan_repro
from autotest_mcp.defects.jira import MockJiraClient
from autotest_mcp.defects.models import Defect, ReproStep
from autotest_mcp.mcp_client import FakeHardwareClient
from autotest_mcp.pipeline import run_repro_diagnose
from autotest_mcp.testing import FakeLLM


def test_filter_whitelist():
    allowed, rejected = filter_whitelist(
        ["test> run", "log> dump", "evil> rm", "test> status"],
        ["test> ", "log> "],
    )
    assert allowed == ["test> run", "log> dump", "test> status"]
    assert rejected == ["evil> rm"]


def test_plan_repro_rejects_non_whitelisted():
    defect = Defect(
        id="X", title="t",
        repro_steps=[ReproStep(action="serial_cmd", target="test> x")],
    )
    plan = plan_repro(defect, FakeLLM(), whitelist=["test> ", "log> "])
    # FakeLLM 里塞了一条 rm -rf /，必须被硬安全门拒掉
    assert "rm -rf /" not in plan.serial_commands
    assert getattr(plan, "_rejected_commands") == ["rm -rf /"]
    assert plan.serial_commands == ["test> enable_button_log"]


def test_mock_jira_loads_example():
    jira = MockJiraClient("config/defects.example.yaml")
    d = jira.get_defect("BUG-123")
    assert d.severity == "critical"
    assert any(s.action == "press_button" for s in d.repro_steps)


@pytest.mark.asyncio
async def test_pipeline_end_to_end_with_fakes():
    jira = MockJiraClient("config/defects.example.yaml")
    defect = jira.get_defect("BUG-123")
    hw = FakeHardwareClient("boardA")
    report = await run_repro_diagnose(
        defect, FakeLLM(), hw,
        board_id="boardA", whitelist=["test> ", "log> ", "repro> "],
    )
    assert report.defect_id == "BUG-123"
    # FakeHardwareClient 的假 log 含 Guru Meditation → 判定复现
    assert report.reproduced is True
    assert "capture" in report.steps_executed
    assert report.diagnosis.root_cause  # 非空
    assert report.diagnosis.confidence == "high"
    # 注入了白名单内的命令
    assert any(c[0] == "capture" and c[1]["inject"] == ["test> enable_button_log"] for c in hw.calls)


@pytest.mark.asyncio
async def test_pipeline_no_elf_passes_raw_log():
    defect = Defect(id="Y", title="t", firmware_ref="")
    report = await run_repro_diagnose(
        defect, FakeLLM(), FakeHardwareClient(),
        whitelist=["test> "],
    )
    # 无 elf → 不符号化，但仍产出诊断
    assert report.diagnosis.root_cause
