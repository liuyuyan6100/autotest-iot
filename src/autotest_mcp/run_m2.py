"""M2 命令行：诊断 → Fixer 产 PR（人工门）→（合并后）rebuild+flash+复测。

本地无 key/无 gh/无板（fake 全流程，含模拟修复生效）:
  python -m autotest_mcp.run_m2 BUG-123 --fake --source /tmp/fw \
      --defects config/defects.example.yaml

真实（Windows + key + gh + 板子）: 先 propose 拿 PR，人 review 合并后再 --retest。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from .config import load_config
from .defects.jira import make_jira
from .fix_pipeline import propose_fix, run_retest
from .git_client import FakeGitClient, GhGitClient
from .llm import LLM, default_client
from .mcp_client import FakeHardwareClient, McpHardwareClient
from .pipeline import run_repro_diagnose
from .run_m1 import _StubLLM  # 复用“无 key”友好报错


def _build_llm(cfg, fake: bool) -> LLM:
    if fake:
        from .testing import FakeLLM

        return FakeLLM()
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return LLM(default_client(), model=cfg.agents.model, effort=cfg.agents.effort)
    return _StubLLM(model=cfg.agents.model, effort=cfg.agents.effort)


def _fake_build(_repo_dir):
    return {"ok": True, "build_dir": "<fake build>"}


def main() -> None:
    ap = argparse.ArgumentParser(description="M2 修复+复测 pipeline")
    ap.add_argument("defect_id")
    ap.add_argument("--config", default="config/boards.yaml")
    ap.add_argument("--defects", default="config/defects.example.yaml")
    ap.add_argument("--board", default="boardA")
    ap.add_argument("--source", default=".", help="固件源码目录（修复落地/编译用）")
    ap.add_argument("--fake", action="store_true", help="假 LLM + 假 git + 假硬件，自动走完复测")
    ap.add_argument("--retest", action="store_true", help="跳过人工门直接复测（假设 PR 已合并）")
    ap.add_argument("--kb", default="", help="知识库 JSON 路径；启用后诊断召回+复测通过沉淀")
    args = ap.parse_args()

    cfg = load_config(args.config)
    llm = _build_llm(cfg, args.fake)
    defect = make_jira(cfg, args.defects).get_defect(args.defect_id)

    from .knowledge.store import FileKnowledgeStore

    knowledge = FileKnowledgeStore(args.kb) if args.kb else None

    hardware_repro = FakeHardwareClient(args.board, panic=True) if args.fake else McpHardwareClient(cfg.mcp.url, cfg.mcp.token, args.board)
    git = FakeGitClient() if args.fake else GhGitClient()

    if args.fake:
        # demo：种一个含已知 old_string 的源文件，让 Fixer 的 patch 能落地
        from pathlib import Path

        src = Path(args.source) / "components/button"
        src.mkdir(parents=True, exist_ok=True)
        (src / "button.c").write_text("void fire(void){ handle->cb(ev); }\n")

    async def run():
        # M1：复现 + 诊断（若开 --kb，召回相似案例注入诊断）
        report = await run_repro_diagnose(
            defect, llm, hardware_repro,
            board_id=args.board, whitelist=cfg.agents.test_command_whitelist,
            addr2line=cfg.tools.addr2line, knowledge=knowledge,
        )
        print(f"[M1] reproduced={report.reproduced}  diagnosis={report.diagnosis.root_cause}")

        # M2-1：Fixer 产 patch → PR（人工门）
        fr = propose_fix(defect, report.diagnosis, source_context="", llm=llm, git=git, repo_dir=args.source)
        print(f"[M2] PR={fr.pr_url}  status={fr.status}  applied={fr.applied}  errors={fr.errors}")

        # M2-2：复测（--fake 或 --retest 才走；否则停在人工门等合并）
        if args.fake or args.retest:
            hw_retest = FakeHardwareClient(args.board, panic=False) if args.fake else McpHardwareClient(cfg.mcp.url, cfg.mcp.token, args.board)
            build_fn = _fake_build if args.fake else _real_build_fn(cfg)
            rt = await run_retest(
                defect, report.plan, args.source, hw_retest, args.board, build_fn=build_fn,
                diagnosis=report.diagnosis, patch=fr.patch, llm=llm, knowledge=knowledge,
            )
            extra = f"  case_id={rt.case_id}" if rt.case_id else ""
            print(f"[M2] retest verdict={rt.verdict} reproduced={rt.reproduced} build_ok={rt.build_ok} detail={rt.detail}{extra}")
        else:
            print("[M2] 停在人工门：人 review & 合并 PR 后，加 --retest 跑复测。")

    asyncio.run(run())


def _real_build_fn(cfg):
    from .tools.builder import build as build_fw

    return lambda src: build_fw(src, idf_version=cfg.tools.idf_version, backend=cfg.tools.builder_backend)


if __name__ == "__main__":
    sys.exit(main())
