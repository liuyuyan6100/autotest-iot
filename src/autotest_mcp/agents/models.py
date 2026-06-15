"""智能体结构化输出模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """一条执行步骤。op 决定 pipeline 调哪个硬件 tool。"""

    op: Literal["flash", "capture", "inject", "press_button", "power_cycle", "wait"]
    arg: str = Field(description="op=flash:固件路径/build目录; press:按键名; inject:命令; wait:秒数")
    note: str = ""


class ReproPlan(BaseModel):
    """ReproPlanner 产出。serial_commands 受白名单约束（pipeline 会强制过滤）。"""

    steps: list[PlanStep]
    serial_commands: list[str] = Field(
        default_factory=list,
        description="需要注入串口的测试模式命令（必须命中白名单前缀）",
    )
    capture_seconds: float = Field(default=10.0, description="抓 log 时长")
    success_criteria: str = Field(default="", description="判定复现成功的条件，如 panic 命中或特定 log 模式")
    max_attempts: int = 3


class Diagnosis(BaseModel):
    """Diagnostician 产出。"""

    root_cause: str
    suspect_files: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    evidence: list[str] = Field(default_factory=list, description="支撑结论的 log/代码证据")
    hypothesis: str = ""
    suggested_next_step: str = ""


class FileEdit(BaseModel):
    """一处代码修改（str_replace 式）。old_string 为空 = 新建文件。"""

    path: str
    old_string: str = ""
    new_string: str


class Patch(BaseModel):
    """Fixer 产出。所有 patch 一律走 PR 人工门（不因 risk_level 自动合并）。"""

    changes: list[FileEdit]
    rationale: str
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    base_branch: str = "main"
