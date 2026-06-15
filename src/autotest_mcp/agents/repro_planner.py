"""ReproPlanner：把结构化缺陷的复现步骤编排成可执行的硬件复现计划。

LLM 负责"把抽象步骤变成针对具体板子的有序执行计划 + 成功判据"；
白名单过滤是硬编码的安全门，不依赖模型自觉。
"""
from __future__ import annotations

from ..defects.models import Defect
from ..llm import LLM
from .models import ReproPlan

SYSTEM = """\
你是嵌入式测试复现规划专家。给你一个缺陷（含结构化复现步骤），产出针对一块 ESP32-S3 板的
可执行复现计划。规则：
- 通常先 flash 固件（用 defect.firmware_ref），再 capture 抓 log；需要时 insert inject 步骤注入测试命令。
- inject 用到的串口命令放进 serial_commands（每条独立），同时放一条 op=inject 的步骤引用说明。
- success_criteria 要可判定：例如"出现 Guru Meditation / Backtrace"或"串口打印 EXPECTED_TOKEN"。
- max_attempts 通常 1-3，复现不稳定的可提高。
只返回结构化结果。"""


def filter_whitelist(commands: list[str], prefixes: list[str]) -> tuple[list[str], list[str]]:
    """返回 (允许的命令, 被拒绝的命令)。命令必须以某个白名单前缀开头。"""
    allowed, rejected = [], []
    for cmd in commands:
        if any(cmd.startswith(p) for p in prefixes):
            allowed.append(cmd)
        else:
            rejected.append(cmd)
    return allowed, rejected


def plan_repro(defect: Defect, llm: LLM, whitelist: list[str]) -> ReproPlan:
    user = (
        f"缺陷 {defect.id}: {defect.title}\n"
        f"严重度: {defect.severity}\n摘要: {defect.summary}\n"
        f"期望: {defect.expected}\n实际: {defect.actual}\n"
        f"固件: {defect.firmware_ref}\n"
        f"结构化复现步骤:\n"
        + "\n".join(f"- {s.action}: {s.target}  {s.note}" for s in defect.repro_steps)
        + f"\n\n允许注入的串口命令前缀白名单: {whitelist}"
    )
    plan = llm.complete_structured(ReproPlan, SYSTEM, user)

    # 硬安全门：拒绝白名单外的串口命令
    allowed, rejected = filter_whitelist(plan.serial_commands, whitelist)
    plan.serial_commands = allowed
    plan._rejected_commands = rejected  # type: ignore[attr-defined]  # 留痕，便于审计
    return plan
