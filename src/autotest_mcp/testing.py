"""测试用桩：假 LLM（按请求的 schema 返回固定结构化结果）。"""
from __future__ import annotations

from autotest_mcp.agents.models import Diagnosis, FileEdit, Patch, PlanStep, ReproPlan
from autotest_mcp.knowledge.models import Case


class FakeLLM:
    """实现 LLM 协议（complete_structured）。无网络、无 key。"""

    def __init__(self) -> None:
        self.model = "fake-model"
        self.effort = "low"
        self.calls: list[str] = []

    def complete_structured(self, schema, system, user, max_tokens=16000):  # type: ignore[no-untyped-def]
        self.calls.append(user[:80])
        name = getattr(schema, "__name__", "")
        if name == "ReproPlan":
            return ReproPlan(
                steps=[
                    PlanStep(op="flash", arg="<firmware_ref>", note="先烧固件"),
                    PlanStep(op="inject", arg="test> enable_button_log"),
                    PlanStep(op="press_button", arg="user"),
                    PlanStep(op="capture", arg="抓 log"),
                ],
                serial_commands=[
                    "test> enable_button_log",   # 命中白名单
                    "rm -rf /",                   # 不命中白名单 → 应被拒绝
                ],
                capture_seconds=5.0,
                success_criteria="出现 Guru Meditation / Backtrace",
                max_attempts=2,
            )
        if name == "Diagnosis":
            return Diagnosis(
                root_cause="按键回调访问已释放的外设句柄",
                suspect_files=["components/button/button.c"],
                confidence="high",
                evidence=["Backtrace 指向 button_callback"],
                suggested_next_step="检查句柄生命周期，回调前判空",
            )
        if name == "Patch":
            return Patch(
                changes=[
                    FileEdit(
                        path="components/button/button.c",
                        old_string="handle->cb(ev);",
                        new_string="if (handle && handle->cb) handle->cb(ev);",
                    )
                ],
                rationale="回调前判空，避免访问已释放句柄",
                risk_level="low",
                base_branch="main",
            )
        if name == "Case":
            return Case(
                defect_id="",
                title="按键回调访问已释放外设句柄导致 panic",
                symptom="长按 USER 键后概率性 StoreProhibited panic",
                root_cause="按键回调使用了已释放的外设句柄",
                fix="回调前对句柄判空",
                suspect_files=["components/button/button.c"],
                success=True,
                keywords=["按键", "panic", "StoreProhibited", "button", "句柄", "callback", "USER"],
            )
        raise ValueError(f"FakeLLM: unknown schema {name}")
