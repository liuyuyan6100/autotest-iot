"""GitClient：把 Fixer 的 patch 落地成 PR（人工门）。

- apply_file_edits：纯函数，把 FileEdit 列表应用到目录，返回 (已应用, 失败)。可单测、不依赖 git。
- GhGitClient：真路径，git 分支/提交/推送 + gh pr create。PR review 即人工门。
- FakeGitClient：无 gh/无仓库时用，记录 patch 并把编辑写进目录便于检查。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Protocol

from .agents.models import Patch


def apply_file_edits(root: str | Path, edits: list) -> tuple[list[str], list[tuple[str, str]]]:
    """应用 FileEdit 列表到 root 目录。返回 (applied_paths, [(path, reason)])。"""
    root = Path(root)
    applied: list[str] = []
    errors: list[tuple[str, str]] = []
    for e in edits:
        p = root / e.path
        try:
            if e.old_string == "":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(e.new_string, encoding="utf-8")
                applied.append(e.path)
                continue
            if not p.exists():
                errors.append((e.path, "file not found"))
                continue
            text = p.read_text(encoding="utf-8")
            if e.old_string not in text:
                errors.append((e.path, "old_string not found"))
                continue
            if text.count(e.old_string) > 1:
                errors.append((e.path, "old_string not unique"))
                continue
            p.write_text(text.replace(e.old_string, e.new_string, 1), encoding="utf-8")
            applied.append(e.path)
        except OSError as exc:
            errors.append((e.path, f"io error: {exc}"))
    return applied, errors


class GitClient(Protocol):
    def propose_patch(self, repo_dir: str, patch: Patch, branch: str | None = None) -> dict[str, Any]: ...


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


class GhGitClient:
    """真路径：apply → git commit/push → gh pr create。需要仓库已 clone、gh 已登录。"""

    def __init__(self, runner=_run) -> None:
        self._run = runner

    def propose_patch(self, repo_dir: str, patch: Patch, branch: str | None = None) -> dict[str, Any]:
        applied, errors = apply_file_edits(repo_dir, patch.changes)
        branch = branch or f"autotest-fix-{patch.risk_level}"

        g = lambda *a: self._run(list(a), repo_dir)  # noqa: E731
        g("git", "checkout", "-b", branch)
        for path in applied:
            g("git", "add", "--", path)
        g("git", "commit", "-m", f"fix({patch.risk_level}): {patch.rationale[:72]}")
        g("git", "push", "-u", "origin", branch)
        pr = g(
            "gh", "pr", "create",
            "--base", patch.base_branch,
            "--head", branch,
            "--title", f"autotest fix [{patch.risk_level}]",
            "--body", patch.rationale,
        )
        pr_url = (pr.stdout or "").strip().splitlines()[-1] if (pr.stdout or "").strip() else ""
        return {
            "pr_url": pr_url,
            "branch": branch,
            "applied": applied,
            "errors": errors,
            "status": "awaiting_review",
        }


class FakeGitClient:
    """无 gh/无仓库时：记录 patch，把编辑写进 repo_dir 便于检查，返回假 PR url。"""

    def __init__(self) -> None:
        self.proposals: list[Patch] = []

    def propose_patch(self, repo_dir: str, patch: Patch, branch: str | None = None) -> dict[str, Any]:
        self.proposals.append(patch)
        applied, errors = apply_file_edits(repo_dir, patch.changes)
        return {
            "pr_url": f"https://example.test/pr/{len(self.proposals)}",
            "branch": branch or f"autotest-fix-{patch.risk_level}",
            "applied": applied,
            "errors": errors,
            "status": "awaiting_review",
        }
