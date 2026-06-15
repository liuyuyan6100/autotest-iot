"""真接口测试：Jira _map_issue/_parse_repro、JiraRestClient(http 注入)、GithubPrChecker(subprocess 注入)、make_jira 工厂。"""
import json
import subprocess

import pytest

from autotest_mcp.config import AppConfig
from autotest_mcp.defects.jira import make_jira
from autotest_mcp.defects.jira_rest import JiraRestClient, _map_issue, _parse_repro
from autotest_mcp.defects.models import ReproStep
from autotest_mcp.git_client import GithubPrChecker


# ---------- _map_issue / _parse_repro ----------

def test_parse_repro_structured_list():
    raw = [
        {"action": "serial_cmd", "target": "test> run", "note": "x"},
        {"action": "press_button", "target": "user"},
        {"action": "rm-rf", "target": "/"},  # 非法 action → 丢弃
    ]
    steps = _parse_repro(raw)
    assert [s.action for s in steps] == ["serial_cmd", "press_button"]
    assert steps[0].target == "test> run"


def test_parse_repro_non_list_returns_empty():
    assert _parse_repro(None) == []
    assert _parse_repro("some text") == []


def test_map_issue_basic():
    issue = {
        "key": "PROJ-42",
        "fields": {
            "summary": "按键 panic",
            "description": "长按 USER 触发",
            "priority": {"name": "High"},
            "status": {"name": "Open"},
        },
    }
    d = _map_issue(issue)
    assert d.id == "PROJ-42"
    assert d.title == "按键 panic"
    assert d.severity == "critical"
    assert d.repro_steps == []


def test_map_issue_with_repro_field():
    issue = {
        "key": "PROJ-1",
        "fields": {
            "summary": "x",
            "description": "",
            "priority": {"name": "Medium"},
            "customfield_10001": [{"action": "wait", "target": "2"}],
        },
    }
    d = _map_issue(issue, repro_field="customfield_10001")
    assert d.severity == "major"
    assert len(d.repro_steps) == 1 and d.repro_steps[0].action == "wait"


# ---------- JiraRestClient (http 注入) ----------

def test_jira_rest_get_and_comment():
    calls = []

    def fake_http(method, url, headers, body):
        calls.append((method, url, body))
        if method == "GET":
            return 200, {"key": "PROJ-9", "fields": {"summary": "s", "description": "d", "priority": {"name": "Low"}}}
        return 201, {"id": "c1"}

    c = JiraRestClient("https://x.atlassian.net", "e@x.com", "tok", http=fake_http)
    d = c.get_defect("PROJ-9")
    assert d.id == "PROJ-9" and d.severity == "minor"
    assert "/rest/api/2/issue/PROJ-9" in calls[0][1]
    assert calls[0][2] is None  # GET 无 body
    # basic auth 头存在
    cred = c._auth()["Authorization"]
    assert cred.startswith("Basic ")
    c.add_comment("PROJ-9", "fixed")
    assert calls[-1][0] == "POST" and calls[-1][2] == {"body": "fixed"}


def test_jira_rest_raises_on_error():
    def bad_http(method, url, headers, body):
        return 404, {"errorMessages": ["nope"]}
    c = JiraRestClient("https://x.atlassian.net", "e", "t", http=bad_http)
    with pytest.raises(RuntimeError):
        c.get_defect("NOPE-1")


# ---------- make_jira 工厂 ----------

def test_make_jira_mock_default():
    cfg = AppConfig()
    j = make_jira(cfg)
    assert j.__class__.__name__ == "MockJiraClient"


def test_make_jira_rest():
    from autotest_mcp.config import JiraConfig

    cfg = AppConfig(jira=JiraConfig(backend="rest", base_url="https://x.atlassian.net", email="e", token="t"))
    j = make_jira(cfg)
    assert j.__class__.__name__ == "JiraRestClient"


# ---------- GithubPrChecker ----------

class _Stub:
    def __init__(self, stdout: str, rc: int = 0) -> None:
        self.stdout = stdout
        self.returncode = rc


def test_pr_merged_true():
    out = json.dumps({"state": "MERGED", "mergedAt": "2026-06-15T00:00:00Z"})
    assert GithubPrChecker(runner=lambda *a, **k: _Stub(out)).is_merged("https://github.com/o/r/pull/1") is True


def test_pr_merged_false_open():
    out = json.dumps({"state": "OPEN", "mergedAt": None})
    assert GithubPrChecker(runner=lambda *a, **k: _Stub(out)).is_merged("https://github.com/o/r/pull/1") is False


def test_pr_merged_gh_failure():
    assert GithubPrChecker(runner=lambda *a, **k: _Stub("", rc=1)).is_merged("any") is False
