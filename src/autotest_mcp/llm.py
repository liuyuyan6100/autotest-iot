"""LLM 封装：结构化输出，Anthropic client 可注入（测试用 fake）。

默认 claude-opus-4-8 + adaptive thinking(summarized) + effort。真实调用由注入的 client 完成；
没装/没 key 时可注入 FakeLLM 返回固定结构化结果，供 pipeline 单测。
"""
from __future__ import annotations

from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "claude-opus-4-8"


class LLM:
    def __init__(self, client: Any | None = None, model: str = DEFAULT_MODEL, effort: str = "high") -> None:
        self.client = client
        self.model = model
        self.effort = effort

    def complete_structured(
        self,
        schema: Type[T],
        system: str,
        user: str,
        max_tokens: int = 16000,
    ) -> T:
        """调用 Claude 并按 pydantic schema 校验返回。client 必须支持 messages.parse。"""
        if self.client is None:
            raise RuntimeError("no LLM client configured (set ANTHROPIC_API_KEY or inject a client)")
        resp = self.client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            output_format=schema,
            messages=[{"role": "user", "content": user}],
        )
        parsed = resp.parsed_output
        if parsed is None:
            raise ValueError(f"LLM returned no structured output; stop_reason={getattr(resp, 'stop_reason', '?')}")
        return parsed


def default_client() -> Any:
    """从环境构造 Anthropic client（ANTHROPIC_API_KEY 等）。"""
    import anthropic

    return anthropic.Anthropic()
