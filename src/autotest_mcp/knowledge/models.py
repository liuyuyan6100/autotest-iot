"""Case：知识库的一条结构化案例（一次闭环的沉淀）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Case(BaseModel):
    id: str = ""
    defect_id: str
    title: str
    symptom: str = Field(default="", description="现象/触发条件")
    root_cause: str = ""
    fix: str = Field(default="", description="修复要点")
    suspect_files: list[str] = Field(default_factory=list)
    success: bool = Field(default=True, description="复测是否通过")
    keywords: list[str] = Field(
        default_factory=list, description="检索用关键词，中英不限"
    )
    created_at: str = ""

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.title,
                self.symptom,
                self.root_cause,
                self.fix,
                " ".join(self.keywords),
                " ".join(self.suspect_files),
            ]
        )
