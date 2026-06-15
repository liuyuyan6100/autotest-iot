"""KnowledgeStore：案例的存储与召回。

- FileKnowledgeStore：JSON 文件 + 关键词/Token 打分。无依赖、离线可跑、可单测（MVP 默认）。
- VectorKnowledgeStore：chromadb 真 RAG（需 pip install -e ".[vector]"，可选）。

二者实现同一协议；pipeline 只依赖协议。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from .models import Case


class KnowledgeStore(Protocol):
    def add(self, case: Case) -> str: ...

    def search(self, query: str, k: int = 5) -> list[Case]: ...


def _tokenize(text: str) -> set[str]:
    """简易分词：英文按词，中文按 2-gram。覆盖无外部分词库的场景。"""
    text = text.lower()
    tokens: set[str] = set(re.findall(r"[a-z0-9_]+", text))
    cjk = re.sub(r"[^一-鿿]", "", text)
    for i in range(len(cjk) - 1):
        tokens.add(cjk[i : i + 2])
    tokens.discard("")
    return tokens


def _score(query_tokens: set[str], case: Case) -> float:
    """召回打分：token 重叠 + 关键词精确命中加权。"""
    ct = _tokenize(case.searchable_text())
    if not ct or not query_tokens:
        return 0.0
    overlap = len(query_tokens & ct)
    kw_hit = sum(1 for kw in case.keywords if kw.lower() in " ".join(query_tokens))
    return overlap + 2.0 * kw_hit


class FileKnowledgeStore:
    """JSON 持久化的关键词召回库。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> list[Case]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Case(**c) for c in data.get("cases", [])]

    def _save(self, cases: list[Case]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"cases": [c.model_dump() for c in cases]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, case: Case) -> str:
        cases = self._load()
        if not case.id:
            case.id = f"case-{len(cases) + 1:04d}"
        cases.append(case)
        self._save(cases)
        return case.id

    def search(self, query: str, k: int = 5) -> list[Case]:
        q = _tokenize(query)
        cases = self._load()
        scored = sorted(((_score(q, c), c) for c in cases), key=lambda x: (-x[0]))
        return [c for s, c in scored if s > 0][:k]

    def all(self) -> list[Case]:
        return self._load()


class VectorKnowledgeStore:
    """chromadb 真 RAG。需要 `pip install -e ".[vector]"` 与（离线外的）embedding。

    默认用 chromadb 内置 embedding；生产可换 voyage/anthropic embedding 与持久 client。
    """

    def __init__(self, path: str | Path, collection: str = "autotest_cases") -> None:
        try:
            import chromadb  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ImportError(
                "VectorKnowledgeStore 需要 chromadb：pip install -e '.[vector]'"
            ) from e
        self._client = chromadb.PersistentClient(path=str(path))
        self._col = self._client.get_or_create_collection(collection)

    def add(self, case: Case) -> str:
        if not case.id:
            case.id = f"case-{self._col.count() + 1:04d}"
        self._col.add(
            ids=[case.id],
            documents=[case.searchable_text()],
            metadatas=[case.model_dump()],
        )
        return case.id

    def search(self, query: str, k: int = 5) -> list[Case]:
        if self._col.count() == 0:
            return []
        res = self._col.query(query_texts=[query], n_results=k)
        out: list[Case] = []
        for meta in (res.get("metadatas") or [[]])[0]:
            out.append(Case(**meta))
        return out
