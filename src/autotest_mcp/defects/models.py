"""结构化缺陷 / 复现步骤模型。

复现步骤是 Jira 结构化字段（已确认），所以这里直接用确定性的结构，不靠 LLM 抽自由文本。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReproStep(BaseModel):
    """一条复现步骤。action 是受控枚举，便于 ReproPlanner 确定性映射。"""

    action: Literal["press_button", "power_cycle", "serial_cmd", "wait", "flash"]
    target: str = Field(description="按键名 / 串口命令 / 固件路径；wait 时为秒数")
    note: str = ""


class Defect(BaseModel):
    id: str
    title: str
    severity: Literal["blocker", "critical", "major", "minor", "trivial"] = "major"
    summary: str = ""
    repro_steps: list[ReproStep] = Field(default_factory=list)
    expected: str = ""
    actual: str = ""
    firmware_ref: str = ""  # 触发该缺陷的固件版本/分支/路径，用于烧录复现
