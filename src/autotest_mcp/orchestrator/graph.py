"""LangGraph 显式状态机编排：重试 / 人工门 / 终态。

替代 M1/M2 的线性 pipeline，补上控制流：
- 复测失败 → 回退重新修复（最多 max_attempts 次），而非单发。
- 显式人工门（interrupt）：PR review 真正暂停等合并，resume 后继续。
- 终态分支：closed（复测通过+沉淀）/ escalated（超限转人工）。
- MemorySaver 检查点：任意阶段暂停可续跑。

节点复用已有的 pipeline / fix_pipeline 函数，依赖（llm/硬件/git/知识库/jira）经工厂注入。
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Callable, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..agents.models import Diagnosis, Patch, ReproPlan
from ..defects.jira import JiraClient
from ..defects.models import Defect
from ..fix_pipeline import FixResult, RetestResult, propose_fix, run_retest
from ..knowledge.store import KnowledgeStore
from ..llm import LLM
from ..mcp_client import HardwareClient
from ..pipeline import RunReport, run_repro_diagnose


class LoopState(TypedDict, total=False):
    defect_id: str
    defect: Defect | None
    plan: ReproPlan | None
    diagnosis: Diagnosis | None
    report: RunReport | None
    fix: FixResult | None
    patch: Patch | None
    retest: RetestResult | None
    attempt: int
    max_attempts: int
    verdict: str  # "closed" | "escalated"
    case_id: str
    notes: Annotated[list[str], operator.add]


@dataclass
class Deps:
    """一次编排的常量依赖（非状态）。"""

    llm: LLM
    hardware: HardwareClient
    git: Any  # GitClient
    knowledge: KnowledgeStore | None
    jira: JiraClient
    repo_dir: str
    board_id: str = "boardA"
    whitelist: list[str] | None = None
    addr2line: str = ""
    source_context: str = ""
    build_fn: Callable[[str], dict[str, Any]] | None = None
    auto_approve: bool = False  # True = 跳过 interrupt（测试/全自动）


def build_orchestrator(deps: Deps, max_attempts: int = 2):
    async def intake(state: LoopState) -> dict:
        defect = deps.jira.get_defect(state["defect_id"])
        return {"defect": defect, "attempt": 0, "max_attempts": max_attempts, "notes": [f"intake {defect.id}"]}

    async def run_m1(state: LoopState) -> dict:
        report = await run_repro_diagnose(
            state["defect"], deps.llm, deps.hardware,
            board_id=deps.board_id,
            whitelist=deps.whitelist,
            addr2line=deps.addr2line,
            knowledge=deps.knowledge,
        )
        return {
            "report": report,
            "diagnosis": report.diagnosis,
            "plan": report.plan,
            "notes": [f"M1 reproduced={report.reproduced}: {report.diagnosis.root_cause}"],
        }

    async def propose_fix_node(state: LoopState) -> dict:
        fr = propose_fix(
            state["defect"], state["diagnosis"], deps.source_context,
            llm=deps.llm, git=deps.git, repo_dir=deps.repo_dir,
        )
        return {"fix": fr, "patch": fr.patch, "notes": [f"fix attempt+1 PR={fr.pr_url} applied={fr.applied}"]}

    async def human_gate(state: LoopState) -> dict:
        if deps.auto_approve:
            return {"notes": ["gate auto-approved"]}
        pr_url = state["fix"].pr_url if state.get("fix") else ""
        approved = interrupt({"need": "review-and-merge PR", "pr_url": pr_url, "attempt": state.get("attempt", 0)})
        return {"notes": [f"gate decision={'approved' if approved else 'rejected'}"]}

    async def retest_node(state: LoopState) -> dict:
        rt = await run_retest(
            state["defect"], state["plan"], deps.repo_dir, deps.hardware, deps.board_id,
            build_fn=deps.build_fn or _noop_build,
            diagnosis=state.get("diagnosis"),
            patch=state.get("patch"),
            llm=deps.llm,
            knowledge=deps.knowledge,
        )
        return {
            "retest": rt,
            "attempt": state.get("attempt", 0) + 1,
            "notes": [f"retest verdict={rt.verdict} reproduced={rt.reproduced}"],
        }

    def decide(state: LoopState) -> str:
        rt = state["retest"]
        if rt.verdict == "pass":
            return "deposit"
        if rt.verdict == "fail" and state["attempt"] < state["max_attempts"]:
            return "propose_fix"  # 回退重试
        return "escalate"  # inconclusive 或 重试耗尽

    async def deposit(state: LoopState) -> dict:
        return {
            "verdict": "closed",
            "case_id": state["retest"].case_id,
            "notes": [f"closed; case={state['retest'].case_id or '(no kb)'}"],
        }

    async def escalate(state: LoopState) -> dict:
        return {"verdict": "escalated", "notes": [f"escalated to human after {state['attempt']} attempt(s)"]}

    g = StateGraph(LoopState)
    g.add_node("intake", intake)
    g.add_node("run_m1", run_m1)
    g.add_node("propose_fix", propose_fix_node)
    g.add_node("human_gate", human_gate)
    g.add_node("retest", retest_node)
    g.add_node("deposit", deposit)
    g.add_node("escalate", escalate)

    g.add_edge(START, "intake")
    g.add_edge("intake", "run_m1")
    g.add_edge("run_m1", "propose_fix")
    g.add_edge("propose_fix", "human_gate")
    g.add_edge("human_gate", "retest")
    g.add_conditional_edges("retest", decide, {
        "deposit": "deposit",
        "propose_fix": "propose_fix",
        "escalate": "escalate",
    })
    g.add_edge("deposit", END)
    g.add_edge("escalate", END)
    return g.compile(checkpointer=MemorySaver())


def _noop_build(_src: str) -> dict[str, Any]:
    return {"ok": True, "build_dir": "<noop build>"}
