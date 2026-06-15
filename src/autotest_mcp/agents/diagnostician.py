"""Diagnostician：读符号化后的 log + 缺陷上下文，给出根因诊断。

输入是已符号化的 log（地址已还原成函数名），所以模型能读懂；不在这一步做执行。
"""
from __future__ import annotations

from ..defects.models import Defect
from ..llm import LLM
from .models import Diagnosis

SYSTEM = """\
你是 ESP32-S3 固件 crash 诊断专家。给你缺陷描述和【已符号化】的串口 log（backtrace 已还原成
函数名+文件:行）。任务：
- 定位最可能的根因（root_cause），列出嫌疑源码文件（suspect_files）。
- 给出证据（evidence）：引用 log 里具体行 / 调用栈。
- 给出下一步建议（suggested_next_step），例如补哪个测试、读哪段代码、怀疑哪个外设时序。
不要编造代码里不存在的符号。若证据不足，confidence 置 low 并说明缺什么。
只返回结构化结果。"""


def diagnose(defect: Defect, symbolized_log: str, llm: LLM, source_snippets: str = "") -> Diagnosis:
    user = (
        f"缺陷 {defect.id}: {defect.title}\n期望/实际: {defect.expected} / {defect.actual}\n"
        f"\n=== 已符号化 log ===\n{symbolized_log[:8000]}\n"
    )
    if source_snippets:
        user += f"\n=== 相关源码片段 ===\n{source_snippets[:8000]}\n"
    return llm.complete_structured(Diagnosis, SYSTEM, user)
