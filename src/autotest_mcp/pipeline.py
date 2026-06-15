"""M1 复现+诊断 pipeline：defect → ReproPlanner → 执行硬件复现 → 符号化 → Diagnostician → 报告。

编排器（未来 LangGraph 状态机的雏形）。执行全交硬件 client；推理全交 LLM；符号化用 M0 的 symbolizer。
LLM、硬件 client、符号化函数都可注入，便于无 key/无板单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .agents.diagnostician import diagnose
from .agents.models import Diagnosis, ReproPlan
from .agents.repro_planner import plan_repro
from .defects.models import Defect
from .knowledge.recall import recall_context
from .knowledge.store import KnowledgeStore
from .llm import LLM
from .mcp_client import HardwareClient
from .tools.builder import _find_artifacts
from .tools.symbolizer import find_addr2line, symbolize as _symbolize


@dataclass
class RunReport:
    defect_id: str
    reproduced: bool
    plan: ReproPlan
    diagnosis: Diagnosis
    log_path: str = ""
    rejected_commands: list[str] = field(default_factory=list)
    steps_executed: list[str] = field(default_factory=list)


def _resolve_elf(firmware_ref: str) -> str | None:
    p = Path(firmware_ref)
    if p.is_dir():
        arts = _find_artifacts(p / "build" if (p / "build").exists() else p)
        return arts.get("elf_path")
    if p.suffix == ".elf":
        return str(p)
    return None


def _default_symbolize(elf: str | None, text: str, addr2line: str = "") -> str:
    if not elf:
        return text  # 无 elf 无法符号化，原样交给诊断（模型仍可读 panic 文本）
    res = _symbolize(elf, text, addr2line=find_addr2line(addr2line))
    return res.get("symbolized") or text


async def run_repro_diagnose(
    defect: Defect,
    llm: LLM,
    hardware: HardwareClient,
    *,
    board_id: str = "boardA",
    whitelist: list[str] | None = None,
    addr2line: str = "",
    symbolize_fn: Callable[[str | None, str], str] | None = None,
    knowledge: "KnowledgeStore | None" = None,
) -> RunReport:
    whitelist = whitelist if whitelist is not None else ["test> ", "log> ", "repro> "]
    sym = symbolize_fn or (lambda elf, text: _default_symbolize(elf, text, addr2line))

    # 1. 规划
    plan = plan_repro(defect, llm, whitelist)
    rejected = getattr(plan, "_rejected_commands", [])

    # 2. 执行：先 flash（若有），再 capture（带 inject）
    steps: list[str] = []
    need_flash = any(s.op == "flash" for s in plan.steps)
    fw_ref = defect.firmware_ref or next(
        (s.arg for s in plan.steps if s.op == "flash"), ""
    )
    if need_flash and fw_ref:
        await hardware.flash(board_id, fw_ref)
        steps.append(f"flash({fw_ref})")

    # 物理动作（按键/控电）在 capture 前执行
    for s in plan.steps:
        if s.op == "press_button":
            await hardware.press_button(board_id, s.arg)
            steps.append(f"press({s.arg})")
        elif s.op == "power_cycle":
            await hardware.power_cycle(board_id)
            steps.append("power_cycle")
        elif s.op == "wait":
            steps.append(f"wait({s.arg})")

    cap = await hardware.capture_serial(
        board_id,
        duration_s=plan.capture_seconds,
        inject=plan.serial_commands or None,
    )
    steps.append("capture")

    # 3. 取 log 文本
    log_text = cap.get("_text") or _read_log(cap.get("log_path", ""))

    # 4. 符号化
    elf = _resolve_elf(fw_ref) if fw_ref else None
    symbolized = sym(elf, log_text)

    # 5. 诊断（注入知识库召回的相似案例）
    prior = recall_context(knowledge, defect)
    diagnosis = diagnose(defect, symbolized, llm, source_snippets=prior)

    reproduced = bool(cap.get("panic_detected") or cap.get("matched_pattern"))
    return RunReport(
        defect_id=defect.id,
        reproduced=reproduced,
        plan=plan,
        diagnosis=diagnosis,
        log_path=cap.get("log_path", ""),
        rejected_commands=rejected,
        steps_executed=steps,
    )


def _read_log(path: str) -> str:
    if not path:
        return ""
    p = Path(path)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
