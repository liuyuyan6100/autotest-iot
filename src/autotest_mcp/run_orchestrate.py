"""编排 CLI：用 LangGraph 状态机跑完整闭环（含重试 + 人工门）。

  # 全 fake 全自动（auto_approve，演示重试/终态）
  python -m autotest_mcp.run_orchestrate BUG-123 --fake --source /tmp/fw --kb /tmp/kb.json

  # 真实：跑到人工门暂停，人合并 PR 后在 stdin 确认续跑
  ANTHROPIC_API_KEY=... python -m autotest_mcp.run_orchestrate BUG-123 --source <仓库>
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from langgraph.types import Command

from .config import load_config
from .defects.jira import MockJiraClient
from .git_client import FakeGitClient, GhGitClient
from .knowledge.store import FileKnowledgeStore
from .llm import LLM, default_client
from .mcp_client import FakeHardwareClient, McpHardwareClient
from .orchestrator import Deps, build_orchestrator
from .run_m1 import _StubLLM


def _build_llm(cfg, fake):
    if fake:
        from .testing import FakeLLM

        return FakeLLM()
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return LLM(default_client(), model=cfg.agents.model, effort=cfg.agents.effort)
    return _StubLLM(model=cfg.agents.model, effort=cfg.agents.effort)


def _real_build_fn(cfg):
    from .tools.builder import build as build_fw

    return lambda src: build_fw(src, idf_version=cfg.tools.idf_version, backend=cfg.tools.builder_backend)


def main() -> None:
    ap = argparse.ArgumentParser(description="LangGraph 状态机编排")
    ap.add_argument("defect_id")
    ap.add_argument("--config", default="config/boards.yaml")
    ap.add_argument("--defects", default="config/defects.example.yaml")
    ap.add_argument("--board", default="boardA")
    ap.add_argument("--source", default=".")
    ap.add_argument("--kb", default="")
    ap.add_argument("--fake", action="store_true")
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--gate", choices=["auto", "stdin", "feishu"], default=None,
                    help="人工门方式：auto(跳过) / stdin(回车确认) / feishu(飞书审批)。不指定时 --fake→auto，否则 stdin")
    args = ap.parse_args()

    if args.gate is None:
        args.gate = "auto" if args.fake else "stdin"

    cfg = load_config(args.config)
    llm = _build_llm(cfg, args.fake)
    jira = MockJiraClient(args.defects)
    knowledge = FileKnowledgeStore(args.kb) if args.kb else None
    # fake：第 1 次 capture(M1复现) 有 panic，之后(复测) 不再 panic → 演示"复现→修复→通过"
    hardware = FakeHardwareClient(args.board, panic_first_n=1) if args.fake else McpHardwareClient(cfg.mcp.url, cfg.mcp.token, args.board)
    git = FakeGitClient() if args.fake else GhGitClient()

    if args.fake:
        from pathlib import Path

        src = Path(args.source) / "components/button"
        src.mkdir(parents=True, exist_ok=True)
        (src / "button.c").write_text("void fire(void){ handle->cb(ev); }\n")

    deps = Deps(
        llm=llm, hardware=hardware, git=git, knowledge=knowledge, jira=jira,
        repo_dir=args.source, board_id=args.board,
        whitelist=cfg.agents.test_command_whitelist, addr2line=cfg.tools.addr2line,
        build_fn=(lambda s: {"ok": True, "build_dir": s}) if args.fake else _real_build_fn(cfg),
        auto_approve=(args.gate == "auto"),
    )
    graph = build_orchestrator(deps, max_attempts=args.max_attempts)
    cfg_thread = {"configurable": {"thread_id": f"{args.defect_id}-1"}}

    async def run():
        result = await graph.ainvoke({"defect_id": args.defect_id}, cfg_thread)
        state = graph.get_state(cfg_thread)
        # 停在人工门（interrupt）时，按 gate 方式续跑
        if state.next and "human_gate" in state.next:
            pr = state.values.get("fix").pr_url if state.values.get("fix") else ""
            if args.gate == "feishu":
                from .feishu import LarkApprovalGate, await_approval_and_resume

                fs = cfg.feishu
                gate = LarkApprovalGate(fs.approval_code, fs.app_id, fs.app_secret, fs.base_url)
                print(f"[gate] 创建飞书审批：fix {pr}")
                decision = await await_approval_and_resume(
                    graph, cfg_thread, gate,
                    title=f"autotest 修复审批 [{args.defect_id}]",
                    content=f"PR: {pr}\n根因: {state.values.get('diagnosis').root_cause if state.values.get('diagnosis') else ''}",
                    approver=fs.approver_open_id,
                    poll_interval=fs.poll_interval, timeout=fs.timeout,
                )
                print(f"[gate] 审批结果: {decision}")
            else:  # stdin
                print(f"[gate] 请 review & 合并 PR: {pr}")
                input("通过回车继续；想拒绝请 Ctrl-C 中止...")
                result = await graph.ainvoke(Command(resume=True), cfg_thread)
        return result

    final = asyncio.run(run())
    print("\n=== 最终状态 ===")
    print(f"verdict: {final.get('verdict')}")
    print(f"attempts: {final.get('attempt')}")
    if final.get("case_id"):
        print(f"case_id: {final.get('case_id')}")
    print("notes:")
    for n in final.get("notes", []):
        print(f"  - {n}")


if __name__ == "__main__":
    sys.exit(main())
