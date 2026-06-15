"""M2 修复+复测 pipeline：诊断 → Fixer 产 patch → PR（人工门）→ build → flash → 复测 → 判定。

人工门：Fixer 产 patch 后开 PR，pipeline 停在 awaiting_review；
人 review 合并后，run_retest 针对已合并的源码 rebuild + flash + 复测，给 pass/fail 判定。

LLM、Git、build、硬件均可注入，无 key/无 gh/无板可单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from .agents.fixer import fix
from .agents.models import Diagnosis, Patch, ReproPlan
from .agents.summarizer import summarize
from .defects.models import Defect
from .git_client import GitClient
from .knowledge.store import KnowledgeStore
from .llm import LLM
from .mcp_client import HardwareClient


@dataclass
class FixResult:
    defect_id: str
    patch: Patch
    pr_url: str
    status: Literal["awaiting_review", "error"]
    applied: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RetestResult:
    defect_id: str
    verdict: Literal["pass", "fail", "inconclusive"]
    build_ok: bool
    reproduced: bool
    log_path: str = ""
    detail: str = ""
    case_id: str = ""  # 沉淀进知识库的案例 id（若有）


def propose_fix(
    defect: Defect,
    diagnosis: Diagnosis,
    source_context: str,
    llm: LLM,
    git: GitClient,
    repo_dir: str,
) -> FixResult:
    """Fixer 产 patch → 开 PR → 停在人工门。不 build/不 flash。"""
    patch = fix(defect, diagnosis, source_context, llm)
    res = git.propose_patch(repo_dir, patch)
    status: Literal["awaiting_review", "error"] = (
        "error" if res.get("errors") and not res.get("applied") else "awaiting_review"
    )
    return FixResult(
        defect_id=defect.id,
        patch=patch,
        pr_url=res.get("pr_url", ""),
        status=status,
        applied=res.get("applied", []),
        errors=res.get("errors", []),
    )


async def run_retest(
    defect: Defect,
    plan: ReproPlan,
    repo_dir: str,
    hardware: HardwareClient,
    board_id: str,
    *,
    build_fn: Callable[[str], dict[str, Any]],
    diagnosis: Diagnosis | None = None,
    patch: Patch | None = None,
    llm: LLM | None = None,
    knowledge: KnowledgeStore | None = None,
) -> RetestResult:
    """假设 patch 已被人 review 合并进 repo_dir：rebuild → flash → 复测 → 判定。

    复测通过且提供 llm+knowledge 时，自动沉淀一条 Case 进知识库。
    """
    build = build_fn(repo_dir)
    if not build.get("ok"):
        return RetestResult(defect.id, "inconclusive", False, False, detail="build failed")

    build_dir = build.get("build_dir") or build.get("flash_args_path") or build.get("bin_path")
    if not build_dir:
        return RetestResult(defect.id, "inconclusive", True, False, detail="no build artifact to flash")

    flash_res = await hardware.flash(board_id, build_dir)
    if isinstance(flash_res, dict) and not flash_res.get("ok", True):
        return RetestResult(defect.id, "inconclusive", True, False, detail="flash failed")

    cap = await hardware.capture_serial(
        board_id,
        duration_s=plan.capture_seconds,
        inject=plan.serial_commands or None,
    )
    reproduced = bool(cap.get("panic_detected") or cap.get("matched_pattern"))
    verdict: Literal["pass", "fail"] = "fail" if reproduced else "pass"

    # 复测通过 → 沉淀进知识库（"越用越聪明"）
    case_id = ""
    if verdict == "pass" and llm is not None and knowledge is not None and diagnosis is not None:
        case = summarize(defect, diagnosis, patch, verdict, llm)
        case_id = knowledge.add(case)

    return RetestResult(
        defect_id=defect.id,
        verdict=verdict,
        build_ok=True,
        reproduced=reproduced,
        log_path=cap.get("log_path", ""),
        case_id=case_id,
    )
