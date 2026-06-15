"""Fixer：根据诊断 + 相关源码，产出最小化的代码修改（str_replace 式 FileEdit）。

只生成结构化 patch，不直接改文件；落地由 GitClient 完成。所有 patch 一律走 PR 人工门。
"""
from __future__ import annotations

from ..defects.models import Defect
from ..llm import LLM
from .models import Diagnosis, Patch

SYSTEM = """\
你是 ESP32-S3 固件修复工程师。给你缺陷描述、根因诊断、相关源码片段，产出【最小化】的代码修改。
规则：
- 用 str_replace 式编辑：每处 FileEdit 给 path + old_string(原文精确片段) + new_string(替换后)。
  old_string 留空 = 新建文件。old_string 必须能在文件里唯一匹配。
- 只改根因相关的最小范围，不要顺手重构、不要加无关防御代码、不要改格式。
- risk_level 反映爆炸半径：涉及中断/驱动/电源/并发=high/critical，纯逻辑/日志=low/medium。
- rationale 说清为什么这么改能消除根因。
若证据不足以安全修改，返回空 changes 并在 rationale 说明缺什么。只返回结构化结果。"""


def fix(defect: Defect, diagnosis: Diagnosis, source_context: str, llm: LLM) -> Patch:
    user = (
        f"缺陷 {defect.id}: {defect.title}\n"
        f"根因诊断: {diagnosis.root_cause}\n"
        f"嫌疑文件: {', '.join(diagnosis.suspect_files)}\n"
        f"诊断证据: {'; '.join(diagnosis.evidence)}\n"
        f"诊断建议: {diagnosis.suggested_next_step}\n"
        f"\n=== 相关源码片段 ===\n{source_context[:8000]}\n"
    )
    return llm.complete_structured(Patch, SYSTEM, user)
