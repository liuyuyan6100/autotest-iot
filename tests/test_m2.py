import asyncio
from pathlib import Path

import pytest

from autotest_mcp.agents.models import Diagnosis, FileEdit, Patch, ReproPlan, PlanStep
from autotest_mcp.defects.models import Defect
from autotest_mcp.fix_pipeline import propose_fix, run_retest
from autotest_mcp.git_client import FakeGitClient, apply_file_edits
from autotest_mcp.mcp_client import FakeHardwareClient
from autotest_mcp.testing import FakeLLM


def test_apply_file_edits_replace_and_create(tmp_path):
    f = tmp_path / "a.c"
    f.write_text("int x = call();\n")
    edits = [
        FileEdit(path="a.c", old_string="call();", new_string="safe_call();"),
        FileEdit(path="new/b.c", old_string="", new_string="void b(void){}\n"),
        FileEdit(path="a.c", old_string="nope", new_string="x"),          # not found
    ]
    applied, errors = apply_file_edits(tmp_path, edits)
    assert applied == ["a.c", "new/b.c"]
    assert len(errors) == 1 and errors[0][0] == "a.c"
    assert "safe_call()" in (tmp_path / "a.c").read_text()
    assert (tmp_path / "new/b.c").exists()


def test_apply_rejects_non_unique(tmp_path):
    f = tmp_path / "a.c"
    f.write_text("dup dup\n")
    applied, errors = apply_file_edits(tmp_path, [FileEdit(path="a.c", old_string="dup", new_string="x")])
    assert applied == []
    assert errors[0][1] == "old_string not unique"


def test_fixer_patch_applies_via_fake_git(tmp_path):
    # 准备一个“源文件”，内容含 FakeLLM 里的 old_string
    (tmp_path / "components/button").mkdir(parents=True)
    (tmp_path / "components/button/button.c").write_text("void fire(){ handle->cb(ev); }\n")

    defect = Defect(id="X", title="t")
    diag = Diagnosis(root_cause="r", suspect_files=["components/button/button.c"], suggested_next_step="判空")
    git = FakeGitClient()
    fr = propose_fix(defect, diag, source_context="", llm=FakeLLM(), git=git, repo_dir=str(tmp_path))

    assert fr.status == "awaiting_review"
    assert fr.pr_url.startswith("https://example.test/pr/")
    assert "components/button/button.c" in fr.applied
    # 编辑真的落地了
    assert "if (handle && handle->cb)" in (tmp_path / "components/button/button.c").read_text()


@pytest.mark.asyncio
async def test_retest_pass_when_panic_gone():
    defect = Defect(id="Y", title="t")
    plan = ReproPlan(steps=[PlanStep(op="capture", arg="")], serial_commands=["test> x"], capture_seconds=2)
    hw = FakeHardwareClient("boardA", panic=False)  # 修复后无 panic
    rt = await run_retest(defect, plan, "/tmp/fw", hw, "boardA", build_fn=lambda src: {"ok": True, "build_dir": src})
    assert rt.verdict == "pass"
    assert rt.reproduced is False


@pytest.mark.asyncio
async def test_retest_fail_when_still_panics():
    defect = Defect(id="Y", title="t")
    plan = ReproPlan(steps=[PlanStep(op="capture", arg="")], capture_seconds=2)
    hw = FakeHardwareClient("boardA", panic=True)  # 修复无效，仍 panic
    rt = await run_retest(defect, plan, "/tmp/fw", hw, "boardA", build_fn=lambda src: {"ok": True, "build_dir": src})
    assert rt.verdict == "fail"
    assert rt.reproduced is True


@pytest.mark.asyncio
async def test_retest_inconclusive_on_build_failure():
    defect = Defect(id="Y", title="t")
    plan = ReproPlan(steps=[], capture_seconds=1)
    hw = FakeHardwareClient("boardA")
    rt = await run_retest(defect, plan, "/tmp/fw", hw, "boardA", build_fn=lambda src: {"ok": False})
    assert rt.verdict == "inconclusive"
    assert rt.build_ok is False
