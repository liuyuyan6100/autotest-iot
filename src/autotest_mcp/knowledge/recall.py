"""召回/沉淀辅助：把知识库案例格式化成上下文，供 agent 注入。"""
from __future__ import annotations

from ..defects.models import Defect
from .models import Case
from .store import KnowledgeStore


def recall_context(store: KnowledgeStore | None, defect: Defect, k: int = 3) -> str:
    """召回与缺陷最相似的 k 条历史案例，格式化成文本；无库或无命中返回空串。"""
    if store is None:
        return ""
    query = f"{defect.title} {defect.summary} {defect.actual}"
    cases = store.search(query, k=k)
    if not cases:
        return ""
    return "=== 历史相似案例（召回） ===\n" + "\n\n".join(format_case(c) for c in cases)


def format_case(c: Case) -> str:
    return (
        f"[{c.id}] {c.title}\n"
        f"  现象: {c.symptom}\n"
        f"  根因: {c.root_cause}\n"
        f"  修复: {c.fix}\n"
        f"  文件: {', '.join(c.suspect_files)}\n"
        f"  成功: {'是' if c.success else '否'}"
    )
