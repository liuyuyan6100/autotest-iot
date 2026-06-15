"""Summarizer：把一次闭环（缺陷+诊断+修复+复测）浓缩成结构化 Case 入知识库。"""
from __future__ import annotations

from datetime import datetime, timezone

from ..defects.models import Defect
from ..knowledge.models import Case
from ..llm import LLM
from .models import Diagnosis, Patch

SYSTEM = """\
你是嵌入式缺陷知识沉淀专家。把一次完整的复测/修复闭环浓缩成一条结构化案例，供未来召回复用。
要求：
- symptom 写清触发条件与现象（让别人一眼判断是否相似）。
- root_cause / fix 用要点式，去粗取精。
- keywords 放高召回价值的中英关键词（组件、外设、错误类型、函数语义），5-10 个。
- success 反映复测是否真的通过。
不要编造闭环里不存在的信息。只返回结构化结果。"""


def summarize(
    defect: Defect,
    diagnosis: Diagnosis,
    patch: Patch | None,
    verdict: str,
    llm: LLM,
) -> Case:
    fix_text = ""
    if patch:
        fix_text = patch.rationale + " | edits: " + ", ".join(c.path for c in patch.changes)
    user = (
        f"缺陷 {defect.id}: {defect.title}\n摘要: {defect.summary}\n"
        f"根因: {diagnosis.root_cause}\n嫌疑文件: {', '.join(diagnosis.suspect_files)}\n"
        f"修复: {fix_text}\n复测结论: {verdict}\n"
    )
    case = llm.complete_structured(Case, SYSTEM, user)
    case.defect_id = defect.id
    case.success = verdict == "pass"
    case.created_at = datetime.now(timezone.utc).isoformat()
    return case
