import asyncio

import pytest

from autotest_mcp.agents.models import Diagnosis, Patch, ReproPlan, PlanStep
from autotest_mcp.defects.models import Defect
from autotest_mcp.fix_pipeline import run_retest
from autotest_mcp.knowledge.models import Case
from autotest_mcp.knowledge.recall import recall_context
from autotest_mcp.knowledge.store import FileKnowledgeStore, _score, _tokenize
from autotest_mcp.mcp_client import FakeHardwareClient
from autotest_mcp.testing import FakeLLM


def _case(title, kw):
    return Case(defect_id="X", title=title, symptom=title, keywords=kw)


def test_tokenize_cjk_bigram_and_ascii():
    t = _tokenize("按键 panic StoreProhibited")
    assert "panic" in t and "storeprohibited" in t and "按键" in t


def test_file_store_add_and_relevance(tmp_path):
    store = FileKnowledgeStore(tmp_path / "kb.json")
    store.add(_case("按键回调 panic", ["按键", "panic", "callback"]))
    store.add(_case("WiFi 断连", ["wifi", "断连"]))

    hits = store.search("长按按键触发 panic", k=2)
    assert hits and "按键" in hits[0].title
    assert "WiFi" not in hits[0].title


def test_recall_context_formats_and_empty(tmp_path):
    store = FileKnowledgeStore(tmp_path / "kb.json")
    store.add(_case("按键 panic", ["按键"]))
    defect = Defect(id="B", title="按键长按 panic", summary="")
    ctx = recall_context(store, defect)
    assert "历史相似案例" in ctx and "按键" in ctx

    assert recall_context(None, defect) == ""


def test_score_keyword_boost():
    c = _case("x", ["按键"])
    q = _tokenize("按键 按键 按键")
    assert _score(q, c) > 0


@pytest.mark.asyncio
async def test_deposit_after_pass(tmp_path):
    store = FileKnowledgeStore(tmp_path / "kb.json")
    defect = Defect(id="BUG-1", title="按键 panic")
    diag = Diagnosis(root_cause="r", suspect_files=["a.c"])
    patch = Patch(changes=[], rationale="fix", risk_level="low")
    plan = ReproPlan(steps=[PlanStep(op="capture", arg="")], capture_seconds=1)
    hw = FakeHardwareClient("boardA", panic=False)  # 复测通过

    rt = await run_retest(
        defect, plan, "/tmp/fw", hw, "boardA",
        build_fn=lambda src: {"ok": True, "build_dir": src},
        diagnosis=diag, patch=patch, llm=FakeLLM(), knowledge=store,
    )
    assert rt.verdict == "pass"
    assert rt.case_id  # 沉淀成功
    assert len(store.all()) == 1
    # 沉淀的案例能被召回
    assert store.search("按键 panic")


@pytest.mark.asyncio
async def test_no_deposit_on_fail(tmp_path):
    store = FileKnowledgeStore(tmp_path / "kb.json")
    defect = Defect(id="BUG-1", title="x")
    plan = ReproPlan(steps=[], capture_seconds=1)
    hw = FakeHardwareClient("boardA", panic=True)  # 仍 panic → 复测失败
    rt = await run_retest(
        defect, plan, "/tmp/fw", hw, "boardA",
        build_fn=lambda src: {"ok": True, "build_dir": src},
        diagnosis=Diagnosis(root_cause="r"), llm=FakeLLM(), knowledge=store,
    )
    assert rt.verdict == "fail"
    assert rt.case_id == ""  # 失败不沉淀
    assert store.all() == []
