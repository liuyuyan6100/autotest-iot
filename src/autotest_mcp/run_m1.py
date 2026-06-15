"""M1 命令行：对一个缺陷单跑"复现 + 诊断"。

真实运行（Windows + API key + 板子）:
  AUTOTEST_TOKEN=... python -m autotest_mcp.run_m1 BUG-123

本地无板/无 key 调试（fake LLM + fake 硬件）:
  python -m autotest_mcp.run_m1 BUG-123 --fake --defects config/defects.example.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from .config import load_config
from .defects.jira import MockJiraClient
from .llm import LLM, default_client
from .mcp_client import FakeHardwareClient, McpHardwareClient
from .pipeline import run_repro_diagnose


class _StubLLM(LLM):
    """无 ANTHROPIC_API_KEY 时的占位：抛清晰错误而非崩溃。"""

    def complete_structured(self, schema, system, user, max_tokens=16000):  # type: ignore[override]
        raise SystemExit(
            "未配置 ANTHROPIC_API_KEY，无法调用 LLM。设置 key 或用 --fake 配合假数据测试 pipeline。"
        )


def _build_llm(cfg, fake: bool) -> LLM:
    if fake:
        from .testing import FakeLLM

        return FakeLLM()
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return LLM(default_client(), model=cfg.agents.model, effort=cfg.agents.effort)
    return _StubLLM(model=cfg.agents.model, effort=cfg.agents.effort)


def main() -> None:
    ap = argparse.ArgumentParser(description="M1 复现+诊断 pipeline")
    ap.add_argument("defect_id")
    ap.add_argument("--config", default="config/boards.yaml")
    ap.add_argument("--defects", default="config/defects.example.yaml", help="mock 缺陷库 yaml")
    ap.add_argument("--board", default="boardA")
    ap.add_argument("--fake", action="store_true", help="用假 LLM + 假硬件（无 key/无板）")
    args = ap.parse_args()

    cfg = load_config(args.config)
    llm = _build_llm(cfg, args.fake)
    jira = MockJiraClient(args.defects)
    defect = jira.get_defect(args.defect_id)

    if args.fake:
        hardware = FakeHardwareClient(args.board)
    else:
        hardware = McpHardwareClient(cfg.mcp.url, cfg.mcp.token, args.board)

    report = asyncio.run(
        run_repro_diagnose(
            defect, llm, hardware,
            board_id=args.board,
            whitelist=cfg.agents.test_command_whitelist,
            addr2line=cfg.tools.addr2line,
        )
    )

    print(f"\n=== RunReport: {report.defect_id} ===")
    print(f"reproduced: {report.reproduced}")
    print(f"steps: {report.steps_executed}")
    if report.rejected_commands:
        print(f"REJECTED serial cmds (非白名单): {report.rejected_commands}")
    print("diagnosis:")
    print(json.dumps(report.diagnosis.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
