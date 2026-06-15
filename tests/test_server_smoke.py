import asyncio

import pytest

from autotest_mcp.config import BoardConfig, load_config
from autotest_mcp.server import build_server


def _cfg():
    return load_config("config/boards.yaml.example")


@pytest.mark.asyncio
async def test_tools_registered():
    mcp, _ = build_server(_cfg())
    names = [t.name for t in await mcp.list_tools()]
    assert set(names) == {
        "list_boards", "symbolize", "build", "flash",
        "capture_serial", "press_button", "power_cycle",
    }


@pytest.mark.asyncio
async def test_list_boards_callable():
    mcp, _ = build_server(_cfg())
    res = await mcp.call_tool("list_boards", {})
    # call_tool 返回 (content, structured)；取 structured
    boards = _structured(res)
    assert boards[0]["id"] == "boardA"


@pytest.mark.asyncio
async def test_symbolize_graceful_without_toolchain():
    mcp, _ = build_server(_cfg())
    res = await mcp.call_tool("symbolize", {"elf_path": "/nonexistent.elf", "text": "Backtrace: 0x40384000"})
    out = _structured(res)
    assert out["addresses_found"] == 1
    assert "error" in out  # 无 addr2line / 无 elf，给出友好错误而非崩溃


def _structured(call_result):
    # mcp call_tool 返回 (content_list, structured_dict)；structured 形如 {'result': <tool 返回值>}
    if isinstance(call_result, tuple) and len(call_result) == 2:
        _, structured = call_result
        if isinstance(structured, dict) and "result" in structured:
            return structured["result"]
        if isinstance(structured, dict):
            return structured
    import json

    first = call_result[0] if isinstance(call_result, list) else call_result
    text = getattr(first, "text", None)
    if text:
        return json.loads(text)
    raise AssertionError(f"cannot parse call_tool result: {call_result!r}")
